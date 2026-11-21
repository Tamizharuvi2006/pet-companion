#pragma once

#include <cstdint>

void bella_distance_init();
bool bella_distance_initialized();
bool bella_distance_has_valid_sample();
uint16_t bella_distance_last_mm();
uint32_t bella_distance_invalid_count();
uint32_t bella_distance_valid_count();
