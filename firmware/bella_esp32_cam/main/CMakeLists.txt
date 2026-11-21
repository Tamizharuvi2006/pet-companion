idf_component_register(
    SRCS "../src/main.cpp" "../src/provisioning.cpp"
    INCLUDE_DIRS "../include"
    REQUIRES driver esp_wifi esp_event esp_netif nvs_flash esp_http_server esp32-camera cjson mbedtls
)
