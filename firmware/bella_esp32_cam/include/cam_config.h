#pragma once

#if __has_include("secrets.h")
#include "secrets.h"
#endif

#ifndef BELLA_CAM_WIFI_SSID
#define BELLA_CAM_WIFI_SSID ""
#endif
#ifndef BELLA_CAM_WIFI_PASSWORD
#define BELLA_CAM_WIFI_PASSWORD ""
#endif
#ifndef BELLA_CAM_TOKEN
#define BELLA_CAM_TOKEN ""
#endif
#ifndef BELLA_CAM_PROFILE_AI_THINKER
#define BELLA_CAM_PROFILE_AI_THINKER 0
#endif

#define BELLA_CAM_MAX_JPEG_BYTES 1000000
