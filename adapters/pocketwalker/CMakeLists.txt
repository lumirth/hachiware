cmake_minimum_required(VERSION 3.20)
project(pw_hachiware CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
# Upstream headers rely on MSVC/MinGW transitively providing size_t.
add_compile_options(-include cstddef)
# Unmodified upstream core, compiled as its desktop Release preset does.
add_subdirectory(${PW_ROOT}/core core)
add_executable(pw-hachiware driver.cpp)
target_link_libraries(pw-hachiware pocketwalker_core)
