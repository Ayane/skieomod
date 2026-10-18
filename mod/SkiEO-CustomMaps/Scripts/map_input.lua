-- Native key binds run on UE4SS's event thread. They only publish input flags;
-- an already registered game-thread loop consumes them without lua_xmove or
-- creating callback registry references while animation is running.
local Input={}
local dispatchers,bindings={},{}
local pointer
local function ready(current)
    return current.generation==current.session._timer_generation and current.session._loading_success==true
end
local function pointer_event(action)
    local current=pointer
    if not current then return end
    if current.requested and action~='close' then return end
    current.action=action;current.requested=true
end
local function drain()
    local current=bindings.F7
    if current and current.requested then
        current.requested=false
        if ready(current) then
            local ok,message=xpcall(function()current.callback();current.session:_sync_state()end,
                function(message)return debug.traceback(tostring(message),2)end)
            if not ok then current.api:log('hotkey F7 failed: '..tostring(message)) end
        end
    end
    current=pointer
    if current and current.requested then
        current.requested=false
        if ready(current) then
            local ok,message=xpcall(function()current.callback(current.action)end,
                function(message)return debug.traceback(tostring(message),2)end)
            if not ok then current.session:log('entity input failed: '..tostring(message)) end
        end
    end
    return false
end
function Input.install()
    -- Register native functions on the long-lived loader state. Keep the
    -- polling callback and its handle rooted for the lifetime of this loader.
    if not Input.poll then
        Input.poll=drain
        if EngineTickAvailable and type(LoopInGameThreadAfterFrames)=='function' then
            Input.poll_handle=LoopInGameThreadAfterFrames(1,Input.poll)
        else
            assert(type(LoopInGameThreadWithDelay)=='function','Game-thread input polling is unavailable')
            Input.poll_handle=LoopInGameThreadWithDelay(16,Input.poll)
        end
    end
    if Key and Key.LEFT_MOUSE_BUTTON and not dispatchers.pointer then
        dispatchers.pointer=function()pointer_event('click')end
        dispatchers.escape=function()pointer_event('close')end
        RegisterKeyBind(Key.LEFT_MOUSE_BUTTON,dispatchers.pointer)
        RegisterKeyBind(Key.ESCAPE,dispatchers.escape)
    end
    local key='F7'
    if dispatchers[key] then return end
    assert(type(RegisterKeyBind)=='function' and Key and Key[key],'Keyboard input is unavailable')
    local dispatch=function()
        local current=bindings[key]
        if current then current.requested=true end
    end
    RegisterKeyBind(Key[key],dispatch)
    dispatchers[key]=dispatch
    if type(RegisterConsoleCommandHandler)=='function' then
        RegisterConsoleCommandHandler('custommap_test_hotkey',function(_,parameters)
            if parameters[1]=='F7' then dispatch() end
            return true
        end)
    end
end
function Input.bind(api,key,callback)
    assert(key=='F7','The map debug hotkey is F7')
    assert(type(callback)=='function','Hotkey callback must be a function')
    assert(dispatchers[key],'Keyboard input was not initialized at loader startup')
    assert(not bindings[key],'Map hotkey is already in use: '..key)
    local session=api._session or api
    local binding={api=api,session=session,generation=session._timer_generation,callback=callback,requested=false}
    bindings[key]=binding
    local function release()
        if bindings[key]==binding then bindings[key]=nil end
    end
    session._cleanups=session._cleanups or {}
    session._cleanups[#session._cleanups+1]=release
    return release
end
-- Internal only: decorative entity inspection owns one mailbox per map.
-- Clicks and Escape follow the same game-thread handoff as F7, including pause.
function Input.bind_pointer(session,callback)
    assert(dispatchers.pointer,'Entity mouse input was not initialized at loader startup')
    assert(type(callback)=='function','Entity input callback must be a function')
    assert(not pointer,'Entity mouse input already belongs to a map')
    local current={session=session,generation=session._timer_generation,callback=callback,requested=false,action='click'}
    pointer=current
    local function release()if pointer==current then pointer=nil end end
    session._cleanups=session._cleanups or {};session._cleanups[#session._cleanups+1]=release
    return release
end
return Input
