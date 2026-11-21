#include "bella_config.h"

static_assert(BELLA_SERVO_ENABLED == 0, "Servo output must be disabled by default");
static_assert(BELLA_SERVO2_GPIO12_ENABLED == 0, "Servo 2 on GPIO12 must be disabled by default");
static_assert(BELLA_GPIO12_STRAP_SAFE_CONFIRMED == 0, "The board strap is not confirmed by software");

int main() { return 0; }
