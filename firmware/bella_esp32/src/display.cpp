#include "bella_config.h"
#include "bella_display.h"
#include "bella_face.h"
#include "bella_device_ws.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include <atomic>
#include <cstdio>
#include <cstring>

static std::atomic<BellaState> status{BellaState::Booting};
static QueueHandle_t events=nullptr;
static const char *names[]={"idle","happy","excited","love","curious","surprised","sad","angry","sleepy","wink","listening","thinking","speaking","offline","error"};
struct FaceEvent { FaceState expression; unsigned duration; unsigned pad; };

bool bella_display_expression(const char *expression,unsigned duration_ms){
    if(!events||!expression||duration_ms<250||duration_ms>5000)return false;
    for(unsigned i=0;i<15;i++)if(std::strcmp(expression,names[i])==0){
        FaceEvent event{static_cast<FaceState>(i),duration_ms,0};
        return xQueueOverwrite(events,&event)==pdPASS;
    }
    return false;
}
void bella_display_touch(unsigned pad){
    if(!events||pad>3)return;
    constexpr FaceState mapping[]={FaceState::Happy,FaceState::Love,FaceState::Curious,FaceState::Wink};
    FaceEvent event{mapping[pad],1800,pad+1};xQueueOverwrite(events,&event);
}
static FaceState conversation(BellaState state){
    switch(state){
        case BellaState::Listening:return FaceState::Listening;
        case BellaState::Processing:return FaceState::Thinking;
        case BellaState::Speaking:return FaceState::Speaking;
        case BellaState::Error:return FaceState::Error;
        case BellaState::Booting:case BellaState::Connecting:case BellaState::Disconnected:return FaceState::Offline;
        default:return FaceState::Idle;
    }
}
static void animate(void*){
    BellaFace face;uint32_t sequence=0,last_report=0,last_touch=0;bool touched=false;
    while(true){
        const uint32_t now=static_cast<uint32_t>(esp_timer_get_time()/1000);
        FaceEvent event{};unsigned pad=0;
        if(xQueueReceive(events,&event,0)==pdPASS){
            if(event.pad==0||!touched||uint32_t(now-last_touch)>=250){
                face.emotion=event.expression;face.until=now+event.duration;pad=event.pad;
                if(pad){touched=true;last_touch=now;}
            }
        }
        face.status=conversation(status.load());face.tick(now,.033f);
        // Driver boundary: consume face geometry here only after TFT verification.
        if(bella_ws_is_ready()&&(pad||uint32_t(now-last_report)>=2000)){
            char report[256];
            std::snprintf(report,sizeof(report),"{\"type\":\"face_report\",\"version\":1,\"face_version\":1,\"sequence\":%lu,\"expression\":\"%s\",\"touch_pad\":%s}",static_cast<unsigned long>(sequence++),names[static_cast<unsigned>(face.state(now))],pad==1?"1":pad==2?"2":pad==3?"3":pad==4?"4":"null");
            bella_ws_send_control(report);last_report=now;
        }
        vTaskDelay(pdMS_TO_TICKS(33));
    }
}
void bella_display_init(){
    events=xQueueCreate(1,sizeof(FaceEvent));
    if(!events||xTaskCreate(animate,"bella_face",4096,nullptr,3,nullptr)!=pdPASS){ESP_LOGE("bella_face","Face task initialization failed");return;}
    ESP_LOGW("bella_face","Animation engine ready; physical TFT driver unverified and disabled");
}
void bella_display_set_state(BellaState state,const char*){status.store(state);}
