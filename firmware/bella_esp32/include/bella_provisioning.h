#pragma once

#include <stdbool.h>

bool bella_provision_load();
bool bella_provision_ready();
const char *bella_provision_wifi_ssid();
const char *bella_provision_wifi_password();
const char *bella_provision_backend_url();
const char *bella_provision_device_id();
const char *bella_provision_device_token();
void bella_provision_start_serial();
