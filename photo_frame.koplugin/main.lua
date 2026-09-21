local Device = require("device")

-- Kindle's WakeupMgr is backed by powerd/LIPC. Other platforms have different
-- suspend lifecycles, and are intentionally out of scope for this first build.
if not Device:isKindle() or not Device:supportsScreensaver() then
    return { disabled = true }
end

local BlitBuffer = require("ffi/blitbuffer")
local DataStorage = require("datastorage")
local ImageWidget = require("ui/widget/imagewidget")
local InfoMessage = require("ui/widget/infomessage")
local InputDialog = require("ui/widget/inputdialog")
local LuaSettings = require("luasettings")
local PathChooser = require("ui/widget/pathchooser")
local ScreenSaverWidget = require("ui/widget/screensaverwidget")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local bit = require("bit")
local ffiUtil = require("ffi/util")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local time = require("ui/time")
local util = require("util")
local _ = require("gettext")
local T = ffiUtil.template

local DEFAULT_INTERVAL_SECONDS = 15 * 60
-- A Kindle may spend close to a minute in screenSaver before ReadyToSuspend.
-- Keep the test alarm far enough in the future to still be valid at that point.
local MIN_INTERVAL_MINUTES = 2
local MAX_INTERVAL_MINUTES = 24 * 60
local MAX_LOG_BYTES = 256 * 1024
local MAX_IMAGES = 5000
local SUPPORTED_SUFFIXES = {
    bmp = true,
    gif = true,
    jpeg = true,
    jpg = true,
    png = true,
    tif = true,
    tiff = true,
    webp = true,
}

local root_dir = DataStorage:getDataDir() .. "/photo_frame"
local default_image_dir = root_dir .. "/images"

local PhotoFrame = WidgetContainer:extend{
    name = "photo_frame",
    is_doc_only = false,
    settings_file = DataStorage:getSettingsDir() .. "/photo_frame.lua",
    log_file = root_dir .. "/photo_frame.tsv",
}

local function sanitizeLogField(value)
    if value == nil then return "" end
    local sanitized = tostring(value):gsub("[\t\r\n]", " ")
    return sanitized
end

local function isoTimestamp()
    return os.date("%Y-%m-%dT%H:%M:%S%z")
end

local function isImage(path)
    local suffix = path:match("%.([^./]+)$")
    return suffix and SUPPORTED_SUFFIXES[suffix:lower()] or false
end

-- Local xorshift PRNG: shuffling does not disturb Lua's process-global RNG.
local function makeRandom(seed)
    local state = bit.tobit(seed)
    if state == 0 then state = 0x6D2B79F5 end
    return function(limit)
        state = bit.bxor(state, bit.lshift(state, 13))
        state = bit.bxor(state, bit.rshift(state, 17))
        state = bit.bxor(state, bit.lshift(state, 5))
        return (bit.band(state, 0x7FFFFFFF) % limit) + 1
    end
end

function PhotoFrame:init()
    util.makePath(root_dir)
    util.makePath(default_image_dir)

    self.settings = LuaSettings:open(self.settings_file)
    if not self.settings:has("enabled") then
        self.settings:saveSetting("enabled", false)
    end
    if not self.settings:has("interval_seconds") then
        self.settings:saveSetting("interval_seconds", DEFAULT_INTERVAL_SECONDS)
    end
    if not self.settings:has("image_dir") then
        self.settings:saveSetting("image_dir", default_image_dir)
    end
    if not self.settings:has("logging_enabled") then
        self.settings:saveSetting("logging_enabled", false)
    end
    self.settings:flush()

    -- WakeupMgr identifies tasks by callback identity, so retain one closure.
    self.wake_callback = function()
        self:_onRtcWake()
    end

    self.ui.menu:registerToMainMenu(self)

    if self.settings:isTrue("enabled") then
        self:_queueNextWake(true)
    end
end

function PhotoFrame:_batteryPercentage()
    local powerd = Device:getPowerDevice()
    if not powerd then return nil end
    local ok, capacity = pcall(function()
        return powerd:getCapacity()
    end)
    if ok then return capacity end
    logger.warn("PhotoFrame: failed to read battery capacity:", capacity)
end

function PhotoFrame:_log(event, image, render_ms, note)
    if not self.settings or not self.settings:isTrue("logging_enabled") then return end
    logger.info("PhotoFrame:", event, image or "", render_ms or "", note or "")

    local attributes = lfs.attributes(self.log_file)
    if attributes and attributes.size and attributes.size >= MAX_LOG_BYTES then
        local old_log = self.log_file .. ".old"
        os.remove(old_log)
        local rotated, rotate_err = os.rename(self.log_file, old_log)
        if not rotated then
            logger.warn("PhotoFrame: cannot rotate diagnostic log:", rotate_err)
        end
    end

    local exists = lfs.attributes(self.log_file, "mode") == "file"
    local handle, err = io.open(self.log_file, "a")
    if not handle then
        logger.warn("PhotoFrame: cannot open log:", err)
        return
    end
    if not exists then
        handle:write("timestamp\tevent\timage\trender_ms\tbattery_percent\tnote\n")
    end
    handle:write(table.concat({
        isoTimestamp(),
        sanitizeLogField(event),
        sanitizeLogField(image),
        sanitizeLogField(render_ms),
        sanitizeLogField(self:_batteryPercentage()),
        sanitizeLogField(note),
    }, "\t"), "\n")
    handle:close()
end

function PhotoFrame:_scanImages()
    local images = {}
    local image_dir = self.settings:readSetting("image_dir", default_image_dir)
    util.findFiles(image_dir, function(path)
        -- Ignore macOS resource forks copied onto the Kindle.
        if isImage(path) and not ffiUtil.basename(path):match("^%._") then
            table.insert(images, path)
        end
    end, true, MAX_IMAGES)
    table.sort(images)
    return images
end

function PhotoFrame:_rebuildPlaylist()
    local playlist = self:_scanImages()
    if #playlist == 0 then
        self.settings:saveSetting("playlist", {})
        self.settings:saveSetting("playlist_index", 1)
        self.settings:flush()
        return playlist
    end

    local generation = self.settings:readSetting("shuffle_generation", 0) + 1
    local random = makeRandom(os.time() + generation * 1103515245 + #playlist * 97)
    for index = #playlist, 2, -1 do
        local other = random(index)
        playlist[index], playlist[other] = playlist[other], playlist[index]
    end

    local last_image = self.settings:readSetting("last_image")
    if #playlist > 1 and playlist[1] == last_image then
        playlist[1], playlist[2] = playlist[2], playlist[1]
    end

    self.settings:saveSetting("playlist", playlist)
    self.settings:saveSetting("playlist_index", 1)
    self.settings:saveSetting("shuffle_generation", generation)
    self.settings:flush()
    return playlist
end

function PhotoFrame:_nextImage()
    local playlist = self.settings:readSetting("playlist", {})
    local index = self.settings:readSetting("playlist_index", 1)

    if #playlist == 0 or index > #playlist then
        playlist = self:_rebuildPlaylist()
        index = 1
    end

    -- Deleted files are skipped. Re-scan after exhausting the saved list.
    while index <= #playlist and lfs.attributes(playlist[index], "mode") ~= "file" do
        index = index + 1
    end
    if index > #playlist then
        playlist = self:_rebuildPlaylist()
        index = 1
    end
    if #playlist == 0 then return nil end

    local image = playlist[index]
    self.settings:saveSetting("playlist_index", index + 1)
    self.settings:saveSetting("last_image", image)
    self.settings:flush()
    return image
end

function PhotoFrame:_preparePortraitScreen()
    local Screen = Device.screen
    local rotation = Screen:getRotationMode()
    if bit.band(rotation, 1) == 1 then
        Device.orig_rotation_mode = rotation
        Screen:setRotationMode(Screen.DEVICE_ROTATED_UPRIGHT)
    end
end

function PhotoFrame:_newImageWidget(image)
    local Screen = Device.screen
    return ImageWidget:new{
        file = image,
        file_do_cache = false,
        width = Screen:getWidth(),
        height = Screen:getHeight(),
        -- nil requests exact dimensions. Device-profiled images already match.
        scale_factor = nil,
        alpha = false,
    }
end

function PhotoFrame:_newScreenSaver(image)
    local image_widget = self:_newImageWidget(image)
    local screen_saver = ScreenSaverWidget:new{
        widget = image_widget,
        background = BlitBuffer.COLOR_WHITE,
        covers_fullscreen = true,
    }
    screen_saver.modal = true
    screen_saver.dithered = true
    return screen_saver, image_widget
end

function PhotoFrame:_renderImage(image)
    local started = time.now()
    local Screensaver = require("ui/screensaver")

    -- Reuse our top-level screensaver window during RTC maintenance wakes. This
    -- avoids emitting a false Resume/OutOfScreenSaver cycle every 15 minutes.
    if self.photo_screen and Screensaver.screensaver_widget == self.photo_screen then
        local image_widget = self:_newImageWidget(image)
        local frame = self.photo_screen[1]
        local previous_image = frame and frame[1]
        frame[1] = image_widget
        self.photo_screen.widget = image_widget
        if previous_image and previous_image.free then
            previous_image:free()
        end
        UIManager:setDirty(self.photo_screen, "full")
    else
        -- The normal Kindle suspend path has already created KOReader's sleep
        -- screen. Replace it once, then keep the replacement for future wakes.
        if Screensaver.screensaver_widget then
            Screensaver:close_widget()
        elseif Device.screen_saver_mode then
            Screensaver:cleanup()
        end

        self:_preparePortraitScreen()
        local screen_saver = self:_newScreenSaver(image)
        self.photo_screen = screen_saver
        Device.screen_saver_mode = true
        Screensaver.screensaver_widget = screen_saver
        Screensaver.screensaver_type = "cover"
        Screensaver.image_file = image
        Screensaver.show_message = false
        Screensaver.screensaver_background = "white"
        UIManager:show(screen_saver, "full")
    end

    -- Drain both paint and refresh queues before returning to Kindle powerd.
    UIManager:forceRePaint()
    UIManager:waitForVSync()
    local render_ms = math.floor(time.to_s(time.since(started)) * 1000 + 0.5)
    self:_log("rendered", image, render_ms)
    return render_ms
end

function PhotoFrame:_renderNextImage()
    local image
    local ok, result = xpcall(function()
        image = self:_nextImage()
        if not image then return false end
        self:_renderImage(image)
        return true
    end, debug.traceback)
    if not ok then
        self:_log("render_error", image, nil, result)
        logger.err("PhotoFrame: render failed:", result)
        return false
    end
    if not result then
        self:_log("no_images", nil, nil, self.settings:readSetting("image_dir"))
        return false
    end
    return result
end

function PhotoFrame:_queueNextWake(remove_existing)
    if not Device.wakeup_mgr then
        self:_log("wakeup_unavailable", nil, nil, "Device.wakeup_mgr is nil")
        return false
    end
    if remove_existing then
        Device.wakeup_mgr:removeTasks(nil, self.wake_callback)
    end
    local interval = self.settings:readSetting("interval_seconds", DEFAULT_INTERVAL_SECONDS)
    Device.wakeup_mgr:addTask(interval, self.wake_callback)
    self:_log("wake_scheduled", nil, nil, interval .. " seconds")
    return true
end

function PhotoFrame:_onRtcWake()
    self:_log("wake")
    local rendered = self:_renderNextImage()

    -- The current WakeupMgr task is removed only after this callback returns.
    -- Adding (without removeTasks) lets WakeupMgr promote the new task safely.
    if rendered and self.settings:isTrue("enabled") then
        self:_queueNextWake(false)
        -- Kindle remains in screenSaver/suspended state during this maintenance
        -- wake. Returning control is the request to powerd to suspend again.
        self:_log("return_to_suspend")
    end
end

function PhotoFrame:onSuspend()
    if not self.settings:isTrue("enabled") then return end
    self:_log("suspend")
    if Device.wakeup_mgr then
        Device.wakeup_mgr:removeTasks(nil, self.wake_callback)
    end
    if self:_renderNextImage() then
        self:_queueNextWake(false)
    end
end

function PhotoFrame:onResume()
    -- A real user resume leaves the screensaver state. RTC maintenance wakes do
    -- not broadcast Resume, so they keep their newly queued task intact.
    self.photo_screen = nil
    if Device.wakeup_mgr then
        Device.wakeup_mgr:removeTasks(nil, self.wake_callback)
    end
    if self.settings:isTrue("enabled") then
        self:_log("user_resume")
    end
end

function PhotoFrame:onCloseWidget()
    if Device.wakeup_mgr then
        Device.wakeup_mgr:removeTasks(nil, self.wake_callback)
    end
end

function PhotoFrame:_setEnabled(enabled)
    self.settings:saveSetting("enabled", enabled)
    self.settings:flush()
    if enabled then
        local images = self:_scanImages()
        if #images == 0 then
            self.settings:saveSetting("enabled", false)
            self.settings:flush()
            if Device.wakeup_mgr then
                Device.wakeup_mgr:removeTasks(nil, self.wake_callback)
            end
            self:_log("no_images", nil, nil, self.settings:readSetting("image_dir"))
            return false, _("No images were found in the photo-frame folder.")
        end
        self:_queueNextWake(true)
        return true
    end
    if Device.wakeup_mgr then
        Device.wakeup_mgr:removeTasks(nil, self.wake_callback)
    end
    self:_log("disabled")
    return true
end

function PhotoFrame:_startNow(touchmenu_instance)
    local ok, message = self:_setEnabled(true)
    if not ok then
        UIManager:show(InfoMessage:new{ text = message })
        return
    end
    if touchmenu_instance then touchmenu_instance:closeMenu() end
    -- Call KOReader's device-level suspend abstraction directly. It schedules
    -- the Kindle Suspend handler for the next UI tick, after the menu closes.
    UIManager:suspend()
end

function PhotoFrame:_chooseFolder(touchmenu_instance)
    UIManager:show(PathChooser:new{
        title = _("Choose the photo-frame folder"),
        path = self.settings:readSetting("image_dir", default_image_dir),
        select_directory = true,
        select_file = false,
        show_files = false,
        onConfirm = function(path)
            self.settings:saveSetting("image_dir", path)
            self.settings:saveSetting("playlist", {})
            self.settings:saveSetting("playlist_index", 1)
            self.settings:flush()
            if touchmenu_instance then touchmenu_instance:updateItems() end
        end,
    })
end

function PhotoFrame:_showIntervalDialog(touchmenu_instance)
    local current_seconds = self.settings:readSetting("interval_seconds", DEFAULT_INTERVAL_SECONDS)
    local current_minutes = math.floor(current_seconds / 60)
    local interval_dialog
    interval_dialog = InputDialog:new{
        title = _("Photo change interval"),
        description = T(_("Enter whole minutes (%1–%2). 720 = 12 hours; 1440 = 24 hours."),
            MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES),
        input = tostring(current_minutes),
        input_type = "number",
        buttons = {
            {
                {
                    text = _("Cancel"),
                    id = "close",
                    callback = function()
                        UIManager:close(interval_dialog)
                    end,
                },
                {
                    text = _("Set interval"),
                    is_enter_default = true,
                    callback = function()
                        local minutes = tonumber(interval_dialog:getInputText())
                        if not minutes or minutes ~= math.floor(minutes)
                            or minutes < MIN_INTERVAL_MINUTES or minutes > MAX_INTERVAL_MINUTES then
                            UIManager:show(InfoMessage:new{
                                text = T(_("Enter a whole number from %1 to %2."),
                                    MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES),
                            })
                            return
                        end
                        self.settings:saveSetting("interval_seconds", minutes * 60)
                        self.settings:flush()
                        if self.settings:isTrue("enabled") then
                            self:_queueNextWake(true)
                        end
                        UIManager:close(interval_dialog)
                        if touchmenu_instance then touchmenu_instance:updateItems() end
                    end,
                },
            },
        },
    }
    UIManager:show(interval_dialog)
    interval_dialog:onShowKeyboard()
end

function PhotoFrame:addToMainMenu(menu_items)
    menu_items.photo_frame = {
        text = _("Photo frame"),
        sorting_hint = "tools",
        sub_item_table = {
            {
                text = _("Automatically change photos"),
                checked_func = function() return self.settings:isTrue("enabled") end,
                callback = function()
                    local enabled = not self.settings:isTrue("enabled")
                    local ok, message = self:_setEnabled(enabled)
                    if not ok then
                        UIManager:show(InfoMessage:new{ text = message })
                    end
                end,
            },
            {
                text_func = function()
                    local seconds = self.settings:readSetting("interval_seconds", DEFAULT_INTERVAL_SECONDS)
                    return T(_("Change photo every: %1 minutes"), math.floor(seconds / 60))
                end,
                keep_menu_open = true,
                callback = function(touchmenu_instance)
                    self:_showIntervalDialog(touchmenu_instance)
                end,
            },
            {
                text = _("Start photo frame and sleep now"),
                callback = function(touchmenu_instance)
                    self:_startNow(touchmenu_instance)
                end,
            },
            {
                text_func = function()
                    return T(_("Photo folder: %1"), self.settings:readSetting("image_dir", default_image_dir))
                end,
                keep_menu_open = true,
                callback = function(touchmenu_instance)
                    self:_chooseFolder(touchmenu_instance)
                end,
            },
            {
                text_func = function()
                    local last = self.settings:readSetting("last_image")
                    return last and T(_("Last photo: %1"), ffiUtil.basename(last)) or _("Last photo: none")
                end,
                enabled_func = function() return false end,
            },
            {
                text = _("Diagnostic logging"),
                keep_menu_open = true,
                checked_func = function()
                    return self.settings:isTrue("logging_enabled")
                end,
                callback = function(touchmenu_instance)
                    self.settings:saveSetting("logging_enabled",
                        not self.settings:isTrue("logging_enabled"))
                    self.settings:flush()
                    if self.settings:isTrue("logging_enabled") then
                        self:_log("logging_enabled")
                    end
                    if touchmenu_instance then touchmenu_instance:updateItems() end
                end,
            },
            {
                text = _("Reset shuffled playlist"),
                keep_menu_open = true,
                callback = function(touchmenu_instance)
                    self.settings:saveSetting("playlist", {})
                    self.settings:saveSetting("playlist_index", 1)
                    self.settings:flush()
                    if touchmenu_instance then touchmenu_instance:updateItems() end
                end,
            },
        },
    }
end

return PhotoFrame
