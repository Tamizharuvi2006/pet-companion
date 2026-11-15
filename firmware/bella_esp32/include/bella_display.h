#pragma once

#include "bella_runtime.h"

void bella_display_init();
void bella_display_set_state(BellaState state, const char *diagnostic = nullptr);
bool bella_display_expression(const char *expression, unsigned duration_ms);
void bella_display_touch(unsigned pad);
