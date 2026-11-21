from app.main import app


def test_browser_and_device_voice_routes_share_one_app_without_aliasing():
    def paths(router):
        for route in router.routes:
            if hasattr(route, 'original_router'):
                yield from paths(route.original_router)
            elif hasattr(route, 'path'):
                yield route.path
    routes = list(paths(app))
    assert routes.count('/ws/chat') == 1
    assert routes.count('/ws/device') == 1
    assert routes.index('/ws/chat') != routes.index('/ws/device')
