-- 상태줄 위에 메뉴 안내줄(Hint) 추가 + 모드 표시를 NOR → Normal 로 변경

-- 안내줄에 표시할 메뉴 (keymap.toml 의 여러 키 단축키 첫 글자)
local HINTS = {
	{ ",", "정렬" },
	{ "g", "이동" },
	{ "c", "복사" },
	{ "m", "줄 표시" },
}
local HELP = { "~", "전체 단축키" }

-- 안내줄 위/아래 여백 (터미널은 줄 단위라 1 = 한 줄)
local PAD_TOP, PAD_BOTTOM = 1, 1

-- Nord 팔레트 (flavors/nord.yazi), 모서리 둥글림 없이 사각 키캡 형태
local S = {
	label = ui.Style():fg("#88C0D0"):bold(),
	key = ui.Style():fg("#88C0D0"):bg("#3B4252"):bold(),
	desc = ui.Style():fg("#D8DEE9"),
	help_key = ui.Style():fg("#EBCB8B"):bg("#3B4252"):bold(),
	help_desc = ui.Style():fg("#4C566A"):italic(),
}

Hint = {
	_id = "hint",
}

function Hint:new(area) return setmetatable({ _area = area }, { __index = self }) end

function Hint:left(compact)
	local spans = {
		ui.Span(" [Menu]  "):style(S.label),
	}
	for _, h in ipairs(HINTS) do
		spans[#spans + 1] = ui.Span(" " .. h[1] .. " "):style(S.key)
		if not compact then
			spans[#spans + 1] = ui.Span(" " .. h[2]):style(S.desc)
		end
		spans[#spans + 1] = ui.Span("   ")
	end
	return ui.Line(spans)
end

function Hint:right()
	return ui.Line {
		ui.Span(" " .. HELP[1] .. " "):style(S.help_key),
		ui.Span(" " .. HELP[2] .. " "):style(S.help_desc),
	}
end

function Hint:reflow() return { self } end

function Hint:redraw()
	local w = self._area.w
	local left, right = self:left(false), self:right()

	-- 창이 좁으면 오른쪽 도움말 → 메뉴 설명 순으로 생략
	if left:width() + right:width() > w then
		right = ui.Line("")
		if left:width() > w then
			left = self:left(true)
		end
	end

	return {
		left:area(self._area),
		right:area(self._area):align(ui.Align.RIGHT),
	}
end

function Root:layout()
	self._chunks = ui.Layout()
		:direction(ui.Layout.VERTICAL)
		:constraints({
			ui.Constraint.Length(1),
			ui.Constraint.Length(Tabs.height()),
			ui.Constraint.Fill(1),
			ui.Constraint.Length(PAD_TOP),
			ui.Constraint.Length(1),
			ui.Constraint.Length(PAD_BOTTOM),
			ui.Constraint.Length(1),
		})
		:split(self._area)
end

function Root:build()
	self._children = {
		Backdrop:new(self._area),
		Header:new(self._chunks[1], cx.active),
		Tabs:new(self._chunks[2]),
		Tab:new(self._chunks[3], cx.active),
		Hint:new(self._chunks[5]),
		Status:new(self._chunks[7], cx.active),
		Modal:new(self._area),
	}
end

-- NOR / SEL / UNS → Normal / Select / Unset
function Status:mode()
	local mode = tostring(self._tab.mode)
	mode = mode:sub(1, 1):upper() .. mode:sub(2)
	local style = self:style()
	return ui.Line {
		ui.Span(th.status.sep_left.open):fg(style.main:bg()):bg(App.bg()),
		ui.Span(" " .. mode .. " "):style(style.main),
		ui.Span(th.status.sep_left.close):fg(style.main:bg()):bg(style.alt:bg()),
	}
end
