idf_component_register(
    SRCS
        "../src/main.cpp"
        "../src/provisioning.cpp"
        "../src/runtime.cpp"
        "../src/wifi.cpp"
        "../src/device_ws.cpp"
        "../src/audio_i2s.cpp"
        "../src/touch.cpp"
        "../src/display.cpp"
        "../src/servo.cpp"
        "../src/distance.cpp"
    INCLUDE_DIRS "../include"
    REQUIRES driver esp_lcd esp_wifi esp_event esp_netif nvs_flash mbedtls esp_websocket_client cjson vl53l0x esp_lcd_ili9341 esp_lcd_st7735
)
