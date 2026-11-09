-- pob_headless/bridge.lua
--
-- Headless Path of Building 2 bridge for poe2-mcp (MIT, original work).
-- Runs under LuaJIT with cwd = <PathOfBuilding-PoE2>/src and speaks
-- newline-delimited JSON on stdin/stdout:
--   -> {"action": "...", "params": {...}}
--   <- {"ok": true, ...} | {"ok": false, "error": "..."}
-- PoB's own logging is routed to stderr so stdout stays pure JSON.
--
-- Usage (done by src/pob/headless.py):  POB_API_STDIO=1 luajit /abs/path/bridge.lua

-- 1. PoB chatters via print()/ConPrintf() during init: send it to stderr.
do
  local err = io.stderr
  print = function(...)
    local parts = {}
    for i = 1, select('#', ...) do parts[i] = tostring((select(i, ...))) end
    err:write(table.concat(parts, '\t') .. '\n')
  end
end

-- 2. Module search paths (PoB ships dkjson etc. under ../runtime/lua).
package.path = '../runtime/lua/?.lua;../runtime/lua/?/init.lua;' .. package.path

-- 3. Boot the unmodified headless wrapper (defines build/newBuild/loadBuildFromXML).
dofile('HeadlessWrapper.lua')

local json = require('dkjson')

local function frame()
  runCallback('OnFrame')
end

local function recalc()
  build.buildFlag = true
  frame()
end

-- Only plain scalars are exported from the calc output tables.
local function scalars(t, wanted)
  local out = {}
  if type(t) ~= 'table' then return out end
  if wanted then
    for _, k in ipairs(wanted) do
      local v = t[k]
      local tv = type(v)
      if tv == 'number' or tv == 'string' or tv == 'boolean' then out[k] = v end
    end
    return out
  end
  for k, v in pairs(t) do
    local tv = type(v)
    if type(k) == 'string' and (tv == 'number' or tv == 'string' or tv == 'boolean') then
      if tv ~= 'number' or (v == v and v ~= math.huge and v ~= -math.huge) then out[k] = v end
    end
  end
  return out
end

local function require_build()
  if not (build and build.calcsTab and build.calcsTab.mainOutput) then
    error('no build loaded (send load_xml first)')
  end
end

local handlers = {}

handlers.ping = function()
  return { ok = true, pong = true, build_loaded = (build and build.calcsTab and build.calcsTab.mainOutput) ~= nil }
end

handlers.load_xml = function(p)
  if type(p.xml) ~= 'string' or #p.xml == 0 then error('xml (string) required') end
  -- PoB2 silently rejects other roots (e.g. PoE1's <PathOfBuilding>); fail loudly instead.
  if not p.xml:find('<PathOfBuilding2', 1, true) then
    error('XML root must be <PathOfBuilding2> (this looks like a PoE1 or non-PoB2 export)')
  end
  local before = build and build.outputRevision
  loadBuildFromXML(p.xml, p.name or 'poe2-mcp')
  build = __mainObject__.main.modes['BUILD'] -- re-bind: SetMode replaces the mode table state
  recalc()
  require_build()
  if not build.targetVersion then
    error('build needs conversion (targetVersion missing/unsupported; PoB2 exports use targetVersion="0_1")')
  end
  local xl = tonumber(p.xml:match('<Build[^>]-%slevel="(%d+)"'))
  if xl and build.characterLevel ~= xl and not build.characterLevelAutoMode then
    error('build did not load (level mismatch: xml ' .. xl .. ' vs engine ' .. tostring(build.characterLevel) .. ')')
  end
  return { ok = true, loaded = true }
end

-- Fresh PoB2-native build (optionally set the level). Useful as a baseline.
handlers.new_build = function(p)
  newBuild()
  build = __mainObject__.main.modes['BUILD']
  if p.level then handlers.set_level({ level = p.level }) end
  recalc()
  require_build()
  return { ok = true }
end

-- Serialise the current build back to PoB2 XML (same writer PoB uses for saving).
handlers.export_xml = function()
  require_build()
  local xml = build:SaveDB('poe2-mcp') -- returns the composed XML text
  if type(xml) ~= 'string' or #xml == 0 then error('export failed') end
  return { ok = true, xml = xml }
end

handlers.get_stats = function(p)
  require_build()
  local out = build.calcsTab.mainOutput
  local main = {}
  local sk = build.calcsTab.mainEnv and build.calcsTab.mainEnv.player and build.calcsTab.mainEnv.player.mainSkill
  if sk and sk.activeEffect and sk.activeEffect.grantedEffect then
    main.skill = sk.activeEffect.grantedEffect.name
  end
  return {
    ok = true,
    level = build.characterLevel,
    class = build.spec and build.spec.curClassName,
    ascendancy = build.spec and build.spec.curAscendClassName,
    main = main,
    stats = scalars(out, p.fields),
  }
end

-- Set PoB Configuration-tab inputs (e.g. enemyLevel, conditionEnemyShocked).
-- Recalculates and returns the stats (optionally restricted to p.fields).
handlers.set_config = function(p)
  require_build()
  local cfg = p.config
  if type(cfg) ~= 'table' then error('config (object) required') end
  for k, v in pairs(cfg) do build.configTab.input[k] = v end
  build.configTab:BuildModList()
  recalc()
  return handlers.get_stats(p)
end

handlers.set_level = function(p)
  require_build()
  local lvl = tonumber(p.level)
  if not lvl then error('level (number) required') end
  -- Mirror PoB's own level EditControl handler (Modules/Build.lua): manual mode, clamp 1..100.
  build.characterLevel = math.min(math.max(lvl, 1), 100)
  build.characterLevelAutoMode = false
  if build.controls and build.controls.characterLevel then
    build.controls.characterLevel:SetText(build.characterLevel)
  end
  build.configTab:BuildModList()
  build.modFlag = true
  recalc()
  return handlers.get_stats(p)
end

-- Per-socket-group gem breakdown straight from the build.
handlers.get_skills = function()
  require_build()
  local groups = {}
  for gi, g in ipairs(build.skillsTab.socketGroupList or {}) do
    local gems = {}
    for _, gem in ipairs(g.gemList or {}) do
      gems[#gems + 1] = {
        name = gem.nameSpec, level = gem.level, quality = gem.quality,
        enabled = gem.enabled, support = gem.gemData and gem.gemData.grantedEffect and gem.gemData.grantedEffect.support or false,
      }
    end
    groups[#groups + 1] = { index = gi, label = g.displayLabel or g.label, enabled = g.enabled, gems = gems }
  end
  return { ok = true, main_group = build.mainSocketGroup, groups = groups }
end

-- Per-skill damage table: for every enabled socket group, make it the main group,
-- recalc and read the offence keys (confirmed against Modules/CalcOffence.lua,
-- PoB2 commit in headless.py POB_COMMIT). The original main group is restored.
local DMG_TYPES = { 'Physical', 'Lightning', 'Cold', 'Fire', 'Chaos' }
local SKILL_KEYS = {
  'TotalDPS', 'FullDPS', 'CombinedDPS', 'TotalDotDPS', 'AverageDamage', 'AverageHit', 'TotalMin', 'TotalMax',
  'CritChance', 'CritMultiplier', 'Speed', 'HitSpeed', 'HitChance', 'AreaOfEffectRadiusMetres', 'Cooldown', 'Duration',
}

handlers.get_skill_table = function(p)
  require_build()
  local original = build.mainSocketGroup
  local skills = {}
  local ok, err = pcall(function()
    for gi, g in ipairs(build.skillsTab.socketGroupList or {}) do
      if g.enabled then
        build.mainSocketGroup = gi
        recalc()
        local out = build.calcsTab.mainOutput
        local sk = build.calcsTab.mainEnv and build.calcsTab.mainEnv.player and build.calcsTab.mainEnv.player.mainSkill
        local name = sk and sk.activeEffect and sk.activeEffect.grantedEffect and sk.activeEffect.grantedEffect.name
        if name then
          local row = scalars(out, SKILL_KEYS)
          row.index = gi
          row.name = name
          row.label = g.displayLabel or g.label
          row.gem_level = sk.activeEffect.level
          row.gem_quality = sk.activeEffect.quality
          local split = {}
          for _, t in ipairs(DMG_TYPES) do
            split[t] = {
              hit_average = out[t .. 'HitAverage'] or 0,
              combined_average = out[t .. 'StoredCombinedAvg'] or 0,
            }
          end
          row.split = split
          skills[#skills + 1] = row
        end
      end
    end
  end)
  build.mainSocketGroup = original
  recalc()
  if not ok then error(err) end
  return { ok = true, main_group = build.mainSocketGroup, original_main_group = original, skills = skills }
end

handlers.quit =function() return { ok = true, quit = true } end

io.write(json.encode({ ok = true, ready = true }), '\n')
io.flush()
while true do
  local line = io.read('*l')
  if not line then break end
  if #line > 0 then
    local msg = json.decode(line)
    local reply
    if type(msg) ~= 'table' then
      reply = { ok = false, error = 'invalid json' }
    else
      local h = handlers[msg.action]
      if not h then
        reply = { ok = false, error = 'unknown action: ' .. tostring(msg.action) }
      else
        local ok, res = pcall(h, msg.params or {})
        reply = ok and res or { ok = false, error = tostring(res) }
      end
    end
    io.write(json.encode(reply), '\n')
    io.flush()
    if msg and msg.action == 'quit' then break end
  end
end
