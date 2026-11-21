#pragma once
#include <cstdint>

// Pure fence logic shared by the real DMA path and host tests.
// A full ring plus one EOF after the final write is a conservative upper bound,
// not the exact final-sample timestamp and never proof of acoustic output.
struct BellaPlaybackFence {
    uint32_t start=0, generation=0;
    bool complete(uint32_t eof,uint32_t current_generation) const {
        return current_generation==generation && uint32_t(eof-start)>=7;
    }
};
