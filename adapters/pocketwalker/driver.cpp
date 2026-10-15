// hachiware bridge for the PocketWalker core (h4lfheart/pocketwalker), built from
// unmodified upstream sources. It runs the body of PocketWalker::Start and
// H838606::Cycle without pacing, applies a hachiware input timeline in physical
// units and exports the observations the core can represent.
//
// Usage: pw-hachiware --firmware F --eeprom F --milliseconds N [--input CSV]
//                     --out DIR [--observe FIELD ...] [--timing]
#define private public
#define protected public
#include "core/pokewalker/pocketwalker.h"
#undef protected
#undef private
#include "core/soc/defines.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Row { uint64_t micros; std::string kind; std::vector<std::string> values; };

std::vector<uint8_t> slurp(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(f), {}};
}

void write_file(const std::filesystem::path& path, const void* data, size_t size) {
    std::ofstream f(path, std::ios::binary);
    f.write(static_cast<const char*>(data), static_cast<std::streamsize>(size));
}

// Microseconds to core cycles; the core counts a fixed 3.6864 MHz system clock.
uint64_t to_cycle(uint64_t micros) { return micros * PHI_CLK / 1000000; }

// Acceleration timeline in micro-g, converted to BMA150 counts at the selected range.
struct TimelineAccel : SampleProvider {
    std::vector<std::pair<uint64_t, std::array<int64_t, 3>>> points;
    const uint64_t* now = nullptr;
    BMA150* sensor = nullptr;
    AccelSample GetSample() override {
        std::array<int64_t, 3> g{0, 0, 0};
        for (const auto& [at, value] : points) {
            if (at > *now) break;
            g = value;
        }
        const int range = (sensor->mem.Read8(BMA150_ADDR_RANGE_BW_REG) >> 3) & 3;
        const int64_t per_g = 256 >> std::min(range, 2);
        auto count = [&](int64_t micro_g) {
            int64_t v = micro_g * per_g / 1000000;
            return static_cast<int16_t>(std::clamp<int64_t>(v, -512, 511));
        };
        return {count(g[0]), count(g[1]), count(g[2])};
    }
};

}  // namespace

int main(int argc, char** argv) {
    std::string firmware, eeprom_path, input, out;
    uint64_t milliseconds = 0;
    std::set<std::string> observe;
    bool timing = false;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) { std::fprintf(stderr, "missing value for %s\n", a.c_str()); std::exit(2); }
            return argv[++i];
        };
        if (a == "--firmware") firmware = next();
        else if (a == "--eeprom") eeprom_path = next();
        else if (a == "--milliseconds") milliseconds = std::stoull(next());
        else if (a == "--input") input = next();
        else if (a == "--out") out = next();
        else if (a == "--observe") observe.insert(next());
        else if (a == "--timing") timing = true;
        else { std::fprintf(stderr, "unknown argument %s\n", a.c_str()); return 2; }
    }
    auto rom_bytes = slurp(firmware);
    auto eeprom_bytes = slurp(eeprom_path);
    if (rom_bytes.size() != ROM_SIZE || eeprom_bytes.size() != EEPROM_SIZE) {
        std::fprintf(stderr, "firmware must be %d bytes and EEPROM %d bytes\n", ROM_SIZE, EEPROM_SIZE);
        return 2;
    }
    std::vector<Row> rows;
    if (!input.empty()) {
        std::ifstream f(input);
        std::string line;
        while (std::getline(f, line)) {
            if (line.empty() || line[0] == '#') continue;
            std::stringstream ss(line);
            std::string field;
            Row row;
            std::getline(ss, field, ',');
            row.micros = std::stoull(field);
            std::getline(ss, row.kind, ',');
            while (std::getline(ss, field, ',')) row.values.push_back(field);
            rows.push_back(row);
        }
    }

    RomBuffer rom{};
    std::memcpy(rom.data(), rom_bytes.data(), ROM_SIZE);
    EepromBuffer eeprom{};
    std::memcpy(eeprom.data(), eeprom_bytes.data(), EEPROM_SIZE);
    PocketWalker walker(rom);
    walker.SetEepromBuffer(eeprom);
    H838606& soc = *walker.soc;

    uint64_t cycle = 0;
    auto accel = std::make_shared<TimelineAccel>();
    accel->now = &cycle;
    accel->sensor = walker.bma150.get();
    std::vector<Row> events;
    // Optical receive pulses become SCI3 bytes at the bit rate selected when a start pulse arrives.
    std::vector<uint64_t> ir_rises;
    int ir_level = 0;
    for (const auto& row : rows) {
        if (row.kind == "accel") {
            accel->points.push_back({to_cycle(row.micros),
                {std::stoll(row.values.at(0)), std::stoll(row.values.at(1)), std::stoll(row.values.at(2))}});
        } else if (row.kind == "ir") {
            int level = std::stoi(row.values.at(0));
            if (level && !ir_level) ir_rises.push_back(to_cycle(row.micros));
            ir_level = level;
        } else if (row.kind == "buttons") {
            events.push_back(row);
        } else {
            std::fprintf(stderr, "unsupported input %s\n", row.kind.c_str());
            return 3;
        }
    }
    if (!accel->points.empty()) {
        walker.bma150->SetSampleProvider(accel);
        accel->SetEnabled(true);
    }

    uint64_t ir_events = 0, interrupt_entries = 0;
    walker.OnTransmitIR([&](uint8_t byte) {
        // SIR output: one pulse (two transitions) for the start bit and each zero data bit.
        ir_events += 2 * (1 + 8 - __builtin_popcount(byte));
    });
    walker.OnSamplePushed([](BuzzerInformation) {});

    const uint64_t end_cycle = milliseconds * PHI_CLK / 1000;
    size_t next_event = 0, next_rise = 0;
    uint64_t frame_ready = UINT64_MAX;
    uint8_t frame_value = 0;
    auto bit_cycles = [&]() -> uint64_t {
        const auto& sci = *soc.sci3;
        return 32ull * (sci.BRR + 1) << (2 * sci.SMR.CKS);
    };
    auto decode_frame = [&]() {
        const uint64_t start = ir_rises[next_rise++];
        const uint64_t t = bit_cycles();
        uint8_t value = 0xFF;
        while (next_rise < ir_rises.size() && ir_rises[next_rise] < start + t * 19 / 2) {
            const uint64_t offset = ir_rises[next_rise] - start;
            const uint64_t bit = (offset + t / 2) / t;
            if (bit >= 1 && bit <= 8) value &= static_cast<uint8_t>(~(1u << (bit - 1)));
            next_rise++;
        }
        frame_value = value;
        frame_ready = start + t * 19 / 2;
    };

    auto t0 = std::chrono::steady_clock::now();
    while (cycle < end_cycle) {
        while (next_event < events.size() && to_cycle(events[next_event].micros) <= cycle) {
            const Row& row = events[next_event++];
            auto set = [&](ButtonType b, const std::string& v) {
                if (std::stoi(v)) walker.PressButton(b); else walker.ReleaseButton(b);
            };
            set(ButtonType::LEFT, row.values.at(0));
            set(ButtonType::CENTER, row.values.at(1));
            set(ButtonType::RIGHT, row.values.at(2));
        }
        if (frame_ready == UINT64_MAX && next_rise < ir_rises.size() && ir_rises[next_rise] <= cycle)
            decode_frame();
        if (frame_ready <= cycle) {
            walker.ReceiveIR(frame_value);
            frame_ready = UINT64_MAX;
        }
        // H838606::Cycle with interrupt acceptance made observable.
        const uint8_t cycles = soc.cpu->Cycle();
        const uint32_t sp = *soc.cpu->reg.SP;
        soc.interrupts->Cycle(soc.cpu);
        if (*soc.cpu->reg.SP != sp) interrupt_entries++;
        if (soc.CKSTPR2.SSUCKSTP) soc.ssu->Cycle(cycles);
        if (soc.CKSTPR1.S3CKSTP) soc.sci3->Cycle(cycles);
        if (soc.CKSTPR1.TB1CKSTP) soc.timer_b1->Cycle(cycles);
        if (soc.CKSTPR2.TWCKSTP) soc.timer_w->Cycle(cycles);
        if (soc.CKSTPR1.RTCCKSTP) soc.rtc->Cycle(cycles);
        if (soc.CKSTPR1.ADCKSTP) soc.adc->Cycle(cycles);
        walker.CyclePeripherals(cycles);
        cycle += cycles;
    }
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now() - t0).count();

    std::filesystem::path dir(out);
    std::filesystem::create_directories(dir);
    if (observe.count("ram")) {
        uint8_t ram[2048];
        for (int i = 0; i < 2048; i++) ram[i] = soc.memory->Read8(0xF780 + i);
        write_file(dir / "ram.bin", ram, sizeof ram);
    }
    if (observe.count("eeprom")) {
        auto e = walker.GetEepromBuffer();
        write_file(dir / "eeprom.bin", e.data(), e.size());
    }
    NT7508DrawInfo draw = walker.GetDrawInfo();
    if (observe.count("lcd")) {
        uint8_t lcd[4096];
        for (int i = 0; i < 4096; i++) lcd[i] = draw.vram.Read8(i);
        write_file(dir / "lcd.bin", lcd, sizeof lcd);
    }
    if (observe.count("pixels")) {
        // The upstream desktop frontend's presentation: palette index from both planes,
        // offset by the initial display line, blank in power save. Equal drive steps.
        std::vector<uint8_t> pixels(96 * 64, 0);
        if (!draw.power_save) {
            for (int y = 0; y < 64; y++) {
                const int row = (y + draw.initial_display_line) % NT7508_GRAPHICS_HEIGHT;
                const int base_page = (row / 8) * NT7508_TOTAL_COLUMNS * NT7508_COLUMN_SIZE;
                for (int x = 0; x < 96; x++) {
                    const int base = base_page + NT7508_COLUMN_SIZE * x;
                    const int index = (((draw.vram.Read8(base) >> (row % 8)) & 1) << 1)
                                    | ((draw.vram.Read8(base + 1) >> (row % 8)) & 1);
                    pixels[y * 96 + x] = static_cast<uint8_t>(index * 85);
                }
            }
        }
        write_file(dir / "pixels.bin", pixels.data(), pixels.size());
    }
    std::ofstream report(dir / "observations.json");
    report << "{\"completed\": " << (cycle >= end_cycle ? "true" : "false") << ", \"fault\": null";
    if (observe.count("er0")) report << ", \"er0\": " << soc.cpu->reg.registers[0];
    if (observe.count("sleeping")) report << ", \"sleeping\": " << (soc.cpu->sleep ? "true" : "false");
    if (observe.count("display_start")) report << ", \"display_start\": " << int(draw.initial_display_line);
    if (observe.count("interrupt_entries")) report << ", \"interrupt_entries\": " << interrupt_entries;
    if (observe.count("ir_events")) report << ", \"ir_events\": " << ir_events;
    if (timing) report << ", \"host_ns\": " << ns << ", \"emulated_cycles\": " << cycle;
    report << "}\n";
    return 0;
}
