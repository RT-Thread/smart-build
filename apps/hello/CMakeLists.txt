cmake_minimum_required(VERSION 3.16)
project(hello C)

set(SMART_BUILD_LINKAGE "mixed" CACHE STRING "Hello linkage: static, dynamic, or mixed")
set_property(CACHE SMART_BUILD_LINKAGE PROPERTY STRINGS static dynamic mixed)

if(NOT SMART_BUILD_LINKAGE MATCHES "^(static|dynamic|mixed)$")
    message(FATAL_ERROR "SMART_BUILD_LINKAGE must be static, dynamic, or mixed")
endif()

function(add_hello_executable target_name)
    add_executable(${target_name} hello.c)
    install(TARGETS ${target_name} RUNTIME DESTINATION bin)
endfunction()

if(SMART_BUILD_LINKAGE STREQUAL "static" OR SMART_BUILD_LINKAGE STREQUAL "mixed")
    add_hello_executable(hello-static)
    target_link_options(hello-static PRIVATE -static)
endif()

if(SMART_BUILD_LINKAGE STREQUAL "dynamic" OR SMART_BUILD_LINKAGE STREQUAL "mixed")
    add_hello_executable(hello-dynamic)
endif()
