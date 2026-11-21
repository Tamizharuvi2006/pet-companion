#pragma once

#include "bella_runtime.h"
#include "bella_face.h"

void bella_display_init();
void bella_display_set_state(BellaState state, const char *diagnostic = nullptr);
bool bella_display_expression(const char *expression, unsigned duration_ms);
void bella_display_touch(unsigned pad);
void bella_display_presence(bool present);
bool bella_display_set_captions_enabled(bool enabled);
bool bella_display_captions_enabled();
bool bella_display_captions_persisted();
void bella_display_append_caption(const char *text);
void bella_display_clear_caption();
// Normalized geometry; a verified driver maps it to its own resolution/rotation.
BellaFaceGeometry bella_display_snapshot();
const char *bella_display_profile_name();
bool bella_display_initialized();
uint32_t bella_display_frame_count();
uint32_t bella_display_error_count();
uint32_t bella_display_last_render_ms();
