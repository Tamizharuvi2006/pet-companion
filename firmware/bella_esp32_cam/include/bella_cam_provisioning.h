#pragma once

#include <stdbool.h>

bool bella_cam_provision_load();
bool bella_cam_provision_ready();
const char *bella_cam_wifi_ssid();
const char *bella_cam_wifi_password();
const char *bella_cam_token();
void bella_cam_provision_start_serial();
