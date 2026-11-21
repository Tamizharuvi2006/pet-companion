#include "bella_face.h"
#include "bella_playback.h"
#include <cassert>
#include <cmath>

int main(){
    BellaFace face;
    assert(face.state(0)==FaceState::Idle);
    const FaceState map[]={FaceState::Happy,FaceState::Love,FaceState::Curious,FaceState::Wink};
    for(unsigned pad=0;pad<4;pad++){
        BellaFace f;f.touch(pad,1000);assert(f.state(1000)==map[pad]);
        f.touch((pad+1)%4,1100);assert(f.state(1100)==map[pad]);
        assert(f.state(2801)==FaceState::Idle);
    }
    face.status=FaceState::Offline;face.touch(0,1000);
    assert(face.state(1100)==FaceState::Happy);assert(face.geometry(1100).offline);
    face.status=FaceState::Speaking;assert(face.state(1100)==FaceState::Speaking);
    face.status=FaceState::Listening;assert(face.state(1100)==FaceState::Listening);
    face.status=FaceState::Thinking;assert(face.state(1100)==FaceState::Thinking);
    for(uint32_t t=1000;t<10000;t+=33){face.tick(t,.033f);auto g=face.geometry(t);assert(std::isfinite(g.openness)&&g.openness>=0&&g.openness<=1.3);}
    BellaFace blink;blink.tick(2890,.1f);assert(blink.openness<1);
    BellaPlaybackFence fence{100,3};assert(!fence.complete(106,3));assert(fence.complete(107,3));assert(!fence.complete(108,4));
    BellaPlaybackFence wrap{0xfffffffc,7};assert(wrap.complete(3,7));
}
