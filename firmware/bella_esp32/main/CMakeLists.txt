idf_component_register(
    SRCS
        "../src/main.cpp"
        "../src/runtime.cpp"
        "../src/wifi.cpp"
        "../src/device_ws.cpp"
        "../src/audio_i2s.cpp"
        "../src/touch.cpp"
        "../src/display.cpp"
        "../src/servo.cpp"
        "../src/distance.cpp"
    INCLUDE_DIRS "../include"
    REQUIRES driver esp_wifi esp_event esp_netif nvs_flash esp_websocket_client cjson vl53l0x
)
