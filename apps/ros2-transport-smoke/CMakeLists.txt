cmake_minimum_required(VERSION 3.16)
project(ros2_transport_smoke C)

set(SMART_BUILD_LINKAGE "mixed" CACHE STRING "Transport smoke linkage")
set_property(CACHE SMART_BUILD_LINKAGE PROPERTY STRINGS static dynamic mixed)

if(NOT SMART_BUILD_LINKAGE MATCHES "^(static|dynamic|mixed)$")
    message(FATAL_ERROR "SMART_BUILD_LINKAGE must be static, dynamic, or mixed")
endif()

function(add_transport_smoke target_name)
    add_executable(${target_name} transport_smoke.c)
    target_compile_options(${target_name} PRIVATE -Wall -Wextra -Werror)
    target_link_libraries(${target_name} PRIVATE pthread rt)
    install(TARGETS ${target_name} RUNTIME DESTINATION bin)
endfunction()

if(SMART_BUILD_LINKAGE STREQUAL "static" OR SMART_BUILD_LINKAGE STREQUAL "mixed")
    add_transport_smoke(ros2-transport-smoke-static)
    target_link_options(ros2-transport-smoke-static PRIVATE -static)
endif()

if(SMART_BUILD_LINKAGE STREQUAL "dynamic" OR SMART_BUILD_LINKAGE STREQUAL "mixed")
    add_transport_smoke(ros2-transport-smoke)
endif()
