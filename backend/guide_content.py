"""In-app multi-language Guide content (F1 / "❓ Guide" dialog).

Pure Python string/dict data with zero Tkinter or business logic —
ported verbatim from the original monolith (promptforgeint.py). Do not
"improve" the content while it lives here; this module is plain data.

Structured multi-language from the start so adding a translation later
is just filling in a dict entry — no changes to the modal/rendering
code itself (that lives in ui/dialogs/guide_dialog.py, Session 12).
Every non-English language is an EXPLICIT placeholder (its own marked
"translation pending" text, not a silent copy of the English section)
so there's never ambiguity about whether a translation actually exists
yet.
"""

GUIDE_LANGUAGES = {
    "en": "English",
    "ru": "Русский",
    "zh": "中文",
    "ja": "日本語",
}

_GUIDE_PENDING_NOTE = {
    "ru": "Перевод этого раздела пока не готов. Ниже — текст на английском.",
    "zh": "本节翻译尚未完成。以下为英文原文。",
    "ja": "このセクションの翻訳はまだ準備中です。以下は英語版です。",
}


def _guide_pending(lang, english_title, english_body):
    """Builds a placeholder section for a not-yet-translated language —
    shows the English content with an explicit note at the top saying
    so, rather than silently presenting English as if it were the
    translation."""
    note = _GUIDE_PENDING_NOTE.get(lang, "Translation pending — showing English below.")
    return english_title, f"[{note}]\n\n{english_body}"


GUIDE_CONTENT = {
    "en": {
        "quick_start": ("Quick start", """\
Welcome! This is the order things actually need to happen in, the first
time you open PromptForge with a library you didn't build yourself.

1. Go to the Library tab. Click through Styles, Characters, Outfits,
   Scenarios, and Tools at the top-left and look at a few entries —
   just to get a feel for what's actually in this library before doing
   anything else. If everything is empty, you haven't pointed
   PromptForge at a populated prompt_forge_data/ folder yet (or you're
   starting from scratch — see "Library & Subfolders" below for how
   entries work).

2. Go to the Builder tab. Pick a Style, add at least one Character (and
   an Outfit for them), optionally a Scenario. Click
   "⚡ Generate prompt and copy" — this works with zero setup, no
   ComfyUI required, and just builds text you can paste anywhere.

3. If you want PromptForge to generate the image for you directly
   (instead of pasting the prompt somewhere else), see "Connecting to
   ComfyUI" below — it's a separate, optional step with its own
   one-time setup.

4. (Optional, only if you downloaded LoRA files for this library) Once
   ComfyUI is connected, go back to the Library tab and click
   "🔍 Check LoRA dependencies" to confirm every LoRA the library
   expects is actually where ComfyUI can find it. This catches "did I
   actually download everything?" before you start generating dozens
   of characters, not after a confusing result on one of them.

5. If you're starting from an existing image instead of a blank prompt
   — editing it, or turning it into a short video — see "Image Edit &
   Img2Video (pipeline modes)" below. It's a mode you switch into from
   the sidebar, not something that needs setting up ahead of time
   (beyond one extra one-time ComfyUI node, covered in that section).

That's the whole loop. Everything else in this guide is detail on one
piece of it."""),

        "library": ("Library & Subfolders", """\
The Library tab holds everything reusable: Styles, Characters, Outfits,
Scenarios, and Tools. Each entry is just a name plus some text (its
"tags") — the Builder pastes that text into the final prompt wherever
you place that entry.

Subfolders are PURELY for browsing. Dragging an entry into a folder, or
organizing your library into "Anime & Cartoon" / "Casual Clothes" / etc.
has zero effect on search, on the Builder's dropdowns, or on which LoRA
is bound to what — an entry's NAME is still the one thing that
identifies it everywhere else in the app. Right-click anywhere in the
list for folder options (New folder, Move to..., rename, delete) — a
right-click on empty space still offers "New folder", just not "Move
to..." (nothing was selected to move).

Canonical Outfits is a special, automatically-managed folder: outfits
you've marked as a character's "canon" look get filed there
automatically, and you can't manually drag an ordinary outfit into it.

A canon outfit can also have an optional display alias: type a label
like "Office Suit" into the Name field on its card and click Save. The
alias is only a human-readable label — it never renames the file, never
changes the real "Character_Canon_N" key, and never appears in prompt
text. The Library list shows it after the real name
("Character — Canon 1 | Office Suit"), while the Builder outfit selector
shows the alias and keeps "Canon N" underneath, so templates, History
and generation still resolve the same file. Search matches both.
Unchecking "canon" hides the alias without deleting it; re-checking
brings it back. Duplicate creates a copy without the alias. On a new canon
outfit the real "Character_Canon_N" name is assigned automatically on Save;
the Library editor does not display it.

Character variations: a character can have variations — alternative
looks such as "human" and "fox-human" that you don't want as separate
characters. Select a saved character and click "Add variation…" in its
Variations card. A variation is a COPY of the character's saved text:
editing the parent later does NOT change variations that already exist.
In the Library list variations appear as child rows under their parent
(they can't be dragged on their own — moving the parent moves them).
A variation's Name field is its label (shown in Builder); the real file
name "<Parent>__V<n>" never changes. Canon outfits are shared with the
parent. A LoRA bound to a variation replaces the parent's; with none, the
parent's is used. Renaming a parent also renames its canon outfits and
variations (you're asked first); deleting a parent deletes them too, with
the counts in the confirmation. In Builder the Who list shows only parent
characters; when the chosen character has active variations a "Variant:"
row appears (default = the parent itself) in both Standard and Custom
templates. In Standard slots every 👁 button previews its own dropdown:
next to Who the character, next to Variant the chosen variation. In a Custom template [Name n] stays the parent's name,
[Description n] uses the chosen variation. An Inactive parent hides its
variations from Builder. Note: an older PromptForge build opened on the
same data shows variations as ordinary characters and may drop their
label/link when it saves them.

Each entry can optionally have: a reference image (drag a file onto the
editor, or click to browse), a source URL (to credit/relocate the
original model), and a bound LoRA (see "LoRA Manager" below for what
that actually does).

Every entry and every folder also carries an Active/Inactive state,
independent of everything above. Inactive entries and inactive folders
are skipped entirely by the Builder's dropdowns — not just shown greyed
out, actually not indexed — so you can turn off a chunk of
characters/styles/outfits you don't need right now without deleting
them. The Library tab's own browsing still shows inactive entries
(dimmed, sorted after their active siblings within the same folder);
only the Builder actually excludes them. Right-click an entry or folder
for "Mark Inactive"/"Mark Active" (works on a multi-selection too), or
use the "Inactive All"/"Active All" buttons at the bottom of the list —
both relabel to show a count and act on your selection when something's
selected, or the whole library when nothing is.

An entry can also carry a video attachment alongside its reference
image — useful for an Image Actions/Video Actions entry (see "Image
Edit & Img2Video" below) where the "reference" is itself a short clip
rather than a still. It plays back through the same embedded player
used everywhere else video shows up in the app."""),

        "tools_category": ("The Tools category", """\
Tools are library entries that usually have NO real prompt text — their
whole reason for existing is a bound LoRA (an anatomy fixer, a hand
detailer, a sharpness LoRA, anything Stable Diffusion effectively can't
do without). Unlike every other category, a Tool can be saved with
completely empty tags.

If a Tool DOES have a short tag (some workflows trigger a specific LoRA
behavior with something like "@fixedanatomy"), you can mark it "Force
this tool's tag to the very start of the prompt" in the Library editor —
that tag then always lands as the very first thing in the assembled
prompt, ahead of Style/Characters/Scenario, no matter how you've
reordered everything else via "Block order...". Tools without that flag
just sit wherever "Tools" falls in your block order, like any other
section.

Tools live in the slide-out panel on the right edge of the Builder
(click the "»" tab to open it) alongside Seed and Resolution — and,
like the rest of that panel, only appear once ComfyUI is connected."""),

        "lora_manager": ("LoRA Manager", """\
Every active Style, Character, Outfit, and Tool that has a LoRA bound to
it in the Library gets pulled into the LoRA Manager automatically,
tagged [A] (automatic). You can also add a LoRA by hand with
"+ Add LoRA", tagged [M] (manual) — useful for a one-off LoRA you don't
want to permanently bind to a library entry.

LoRA has its own page in the sidebar ("⚙️ LoRA") rather than living
inside the Builder — open it any time to see or adjust every active
slot without leaving that page to go work on Characters/Scenario. Your
slots and strengths persist between sessions.

Before every "🎨 Generate in ComfyUI", every active slot's LoRA name is
checked against ComfyUI's own live LoRA list — a missing file is caught
right there, before anything is submitted, instead of silently being
skipped mid-generation."""),

        "comfyui": ("Connecting to ComfyUI", """\
Direct generation is entirely optional — "⚡ Generate prompt and copy"
always works with zero ComfyUI setup. Connecting unlocks
"🎨 Generate in ComfyUI" (submit and watch it generate without leaving
PromptForge), the Negative prompt section, the LoRA Manager, and the
generation queue.

Setup: install the companion PromptForge Connection custom node package
into ComfyUI/custom_nodes/, place a PromptForge Connector node somewhere
in your ComfyUI graph, set the host/port on the Settings page (sidebar),
then click "Run" in the sidebar footer to connect (it becomes
"Disconnect" once connected).

IMPORTANT — generation always targets the LAST ACTIVE workflow tab in
your browser. PromptForge has no concept of "which workflow you meant":
it asks the bridge for whatever ComfyUI graph was most recently active
in the browser, and submits there. If you have two workflows open and
clicked over to a different tab just to glance at it, your next
generation goes to THAT one, LoRAs included. This holds even if you
close the browser tab, close the browser entirely, or kill the browser
process afterward — ComfyUI keeps using whichever workflow was last
active. That also means you can free up the RAM a browser tab uses
once you've confirmed the right workflow is active, without affecting
generation at all.

Live preview frames depend entirely on ComfyUI's own Settings → Comfy →
Execution → Live preview method setting — if it's set to "none", no
frames arrive, and that's not something PromptForge controls."""),

        "pipeline_modes": ("Image Edit & Img2Video (pipeline modes)", """\
Builder isn't only for building an image from scratch. A small mode
switch under the ⚡ Builder icon in the sidebar cycles between three
pipeline modes — T2I (Text → Image, the default), I2I (Image → Image),
and I2V (Image → Video) — and that control works from anywhere in the
app, not just while Builder is the open tab; toggling it while Library
is open, for instance, immediately narrows Library's category bar to
match without needing to switch tabs first.

I2I and I2V both need one extra piece of one-time ComfyUI setup beyond
the Connector node from "Connecting to ComfyUI" above: a
**PromptForgeImageInput** node wired into your i2i/i2v graph, the same
way you already wire in the Connector or the Multi LoRA Loader. It's
what lets PromptForge push an input image into ComfyUI directly from
its own UI — you never need to Alt-Tab into the browser and use
ComfyUI's own LoadImage widget.

Switching into I2I or I2V replaces the usual Style/Characters/Scenario
column with an input-image drop zone at the top — drag a file onto it
or click to browse — followed by an Actions section. Actions are
Library entries from the new Image Actions / Video Actions categories
(plus any Custom templates you've built for i2i/i2v specifically) —
think of them as the i2i/i2v equivalent of Style/Scenario: purpose-built
prompt text for editing an existing image rather than describing a new
one from nothing. Tools still work the same way they do in T2I, in the
same slide-out panel.

Generations in I2V mode queue and run exactly like image generations do
(see "The generation queue" below) — they just take longer and produce
a video instead of a PNG. Results play back through a shared embedded
video player wherever they show up — Builder's result panel, History,
and the Gallery tab, which also generates an automatic poster-frame
thumbnail for each video so it doesn't sit looking broken next to image
thumbnails."""),

        "queue": ("The generation queue", """\
Clicking "🎨 Generate in ComfyUI" always succeeds immediately — it adds
your current prompt, seed, resolution, and LoRA snapshot to a queue
rather than refusing if something is already generating. Everything
about that click (including which LoRAs and strengths are active right
then) is frozen into that queue entry — changing a LoRA strength
afterward only affects FUTURE clicks, never one already queued.

Exactly one job runs with ComfyUI at a time; queued items wait their
turn and start automatically as each one finishes. "⏹ Stop" cancels
only the one currently running, then the next queued item starts
automatically — it never touches anything still waiting. "🗑 Clear
queue" removes everything still WAITING, but never the one already
generating (matching how ComfyUI's own built-in queue UI behaves) — use
Stop for that one specifically.

The small "📋 N queued" counter next to Generate is there so a rapid
flurry of clicks has visible confirmation that they actually landed,
instead of wondering if anything happened."""),

        "history_gallery": ("History & Gallery", """\
Every prompt you generate is saved to History automatically. An image is
attached only when the generation actually ran through ComfyUI
("Generate in ComfyUI"); prompts you merely built and copied are still
kept, but they appear under "All" and have no picture.

Two filters sit above the list: "Generated Images" (the default) lists
only entries with an image, "All" lists every saved prompt. A missing
file does not remove the entry — the preview says "Image file no longer
available" and only "Open folder" stays active. If ComfyUI's output
folder has never been seen by this installation, the preview says
"Connect to ComfyUI to view this image" instead; the folder is
remembered in settings once you have connected, so earlier sessions'
images normally show up straight after a restart.

Selecting an entry shows the image (or video) preview, the prompt text,
and — when that data exists — three detail cards below it: LoRA (name
and strength for each one used), Generation (resolution, seed, steps)
and Negative prompt, plus "Open image" and "Open folder" buttons that
use the same "last known link" logic as the Gallery's own magnifier
icon. Every copyable value has a small clipboard button: the prompt,
each LoRA line, Resolution, Seed and the whole Negative prompt. Steps
deliberately has none (there is nothing to reuse it for). Clicking a
button puts exactly that value on the clipboard and flashes a check mark.

The Gallery tab shows every image AND video generated through ComfyUI
THIS session as a thumbnail — hover to reveal it in your file explorer,
click to open it full-size. Videos get an automatically-generated
poster-frame thumbnail so they don't sit looking like a broken image
next to real ones, and clicking one opens it in the same embedded
player used everywhere else video shows up in the app (see "Image Edit
& Img2Video" above), not your OS's default video app."""),

        "settings": ("Settings", """\
The Settings page (sidebar) is where ComfyUI's host/port live — that
used to sit inside the Builder tab and moved here instead. It's also
where theme (Dark, Light, or a fully custom palette), notification
sounds, and prompt assembly are configured; see "Sounds & Custom
Themes" below for what the Custom theme option and the Sounds card
actually do.

**Multi-character wrapper.** The Prompt assembly card adds an optional
wrapper for the Standard template, off by default. With two or more
characters selected, each character's tags and outfit can be enclosed
in their own pair — round `( … )`, square `[ … ]`, pipe `| … |`, or any
custom prefix/suffix you type in. The period stays outside the pair,
so a wrapped prompt reads like `First: (tags, outfit).` A single
character is never wrapped, and Custom templates are not affected. This
only changes how the text is grouped. Custom needs both a prefix and a
suffix — if either is empty, the wrapper stays off."""),

        "sounds_and_themes": ("Sounds & Custom Themes", """\
Both live on the same Settings page (sidebar) as the ComfyUI
connection, in their own cards.

**Theme.** Alongside the original Dark/Light toggle there's now a
third option, Custom — two color pickers (Base, Accent) plus a toggle
for whether Custom should lean toward the light or dark end of the
derived palette. Every role in the app (cards, borders, both button
states, the title bar) derives from those two colors and updates live
as you move the pickers, with automatic contrast-safe text color so
even an intentionally awkward combination (very light base + very
light accent) stays readable. You can also upload a background image
for the Custom theme, with a fit-mode choice and an optional opacity
slider — cards and panels keep their own solid backgrounds on top of
it, so there's no automatic legibility protection; that's a deliberate
choice, not a bug, if a busy image makes some corner harder to read at
low opacity.

**Sounds.** Three independently configurable notification sounds —
"gen_ready" (a generation finished and its preview image is ready to
look at), "image_saved" (fires alongside gen_ready today, kept as a
separate setting in case that ever changes), and "entry_added"
(something got saved to History or to the Library). Each one defaults
to None (silent) and can be set to Default (a short bundled chime) or
any number of your own uploaded sounds, WAV only — the file picker
won't even offer other formats, since reliable playback of compressed
audio can't be guaranteed across every machine. Add a sound via the
dropdown's "+ Add Sound…" row; delete one via the small "✕" that
appears next to its name inside the open dropdown, no need to select it
first. Each sound has its own volume slider, disabled whenever that
action is set to None. If a custom sound file ever goes missing from
disk (moved or deleted outside PromptForge), the affected action
quietly falls back to None the next time you launch the app, with a
one-time notice telling you which one changed — never a silent failure
at generation time."""),

    },
    "ru": {
        "quick_start": ("Быстрый старт", """\
Добро пожаловать! Это порядок, в котором нужно делать всё при первом запуске
PromptForge с чужой библиотекой.

1. Откройте вкладку Library. Кликните по Styles, Characters, Outfits, Scenarios
   и Tools слева сверху и посмотрите несколько записей — просто чтобы понять,
   что вообще в этой библиотеке, перед тем как что-то делать. Если везде пусто,
   вы ещё не указали PromptForge на папку prompt_forge_data/ (или стартуете с нуля —
   см. "Library & Subfolders" ниже, как это работает).

2. Откройте вкладку Builder. Выберите Style, добавьте хотя бы одного Character
   (и Outfit для него), опционально Scenario. Кликните "⚡ Generate prompt and copy" —
   это работает без всяких настроек ComfyUI, просто генерирует текст, который
   можно вставить куда угодно.

3. Если хотите, чтобы PromptForge сгенерировал изображение прямо сейчас
   (вместо того чтобы просто скопировать промпт), см. "Connecting to ComfyUI"
   ниже — это отдельная опциональная настройка с собственной инструкцией.

4. (Опционально, только если вы скачали LoRA файлы) Как только ComfyUI
   подключится, вернитесь на вкладку Library и кликните
   "🔍 Check LoRA dependencies" — это проверит, что все нужные LoRA находятся там,
   где их может найти ComfyUI. Лучше узнать про недостающие файлы до того, как
   вы сгенерируете кучу результатов.

5. Если вы начинаете с уже готового изображения, а не с пустого промпта —
   редактируете его или превращаете в короткое видео — см. "Image Edit &
   Img2Video (pipeline modes)" ниже. Это режим, в который вы переключаетесь
   из сайдбара, а не то, что нужно настраивать заранее (кроме одной
   дополнительной разовой ноды в ComfyUI, описанной в этом разделе).

Вот весь цикл. Всё остальное в этом гайде — детали."""),

        "library": ("Библиотека и подпапки", """\
Вкладка Library хранит всё переиспользуемое: Styles, Characters, Outfits,
Scenarios и Tools. Каждая запись — это просто имя плюс текст ("теги"). Builder
вставляет этот текст в финальный промпт, куда бы вы ни поместили эту запись.

Подпапки — ТОЛЬКО для просмотра. Перемещение записи в папку или организация
библиотеки в "Anime & Cartoon" / "Casual Clothes" и т.д. совсем не влияет на
поиск, на выпадающие списки Builder или на привязку LoRA — имя записи всё равно
остаётся единственным идентификатором во всём приложении. Кликните правой кнопкой
в списке для опций папок (New folder, Move to, rename, delete) — клик на пустом месте
тоже предлагает "New folder", но не "Move to" (нечего перемещать).

Canonical Outfits — это специальная, автоматически управляемая папка: outfits,
которые вы отметили как "канонический" вид персонажа, автоматически там появляются,
и вы не можете вручную переместить туда обычный outfit.

У канонического outfit может быть необязательная подпись (alias): введите,
например, "Office Suit" в поле Name на его карточке и нажмите Save. Это только
удобная для человека подпись — она никогда не переименовывает файл, не меняет
настоящее имя "Character_Canon_N" и не попадает в текст промпта. В списке
Library она показывается после настоящего имени
("Character — Canon 1 | Office Suit"), а в селекторе outfit в Builder видна
подпись, тогда как внутри хранится "Canon N" — поэтому шаблоны, History и
генерация продолжают находить тот же файл. Поиск находит и то, и другое.
Снятие галочки "canon" скрывает подпись, не удаляя её; повторная установка
возвращает её. Duplicate создаёт копию без подписи. У нового canon-наряда
настоящее имя «Character_Canon_N» присваивается автоматически при Save;
редактор Library его не показывает.

Вариации персонажа: у персонажа могут быть вариации — альтернативные
облики вроде «human» и «fox-human», которые не хочется делать отдельными
персонажами. Выберите сохранённого персонажа и нажмите «Add variation…» в
карточке Variations. Вариация — это КОПИЯ сохранённого текста персонажа:
последующие правки родителя НЕ меняют уже созданные вариации.
В списке Library вариации показаны дочерними строками под родителем (их
нельзя перетаскивать отдельно — вместе с родителем переезжают и они).
Поле Name у вариации — её подпись (её видно в Builder); настоящее имя
файла «<Parent>__V<n>» не меняется. Canon-наряды общие с родителем.
LoRA, привязанная к вариации, заменяет LoRA родителя; если своей нет —
берётся родительская. Переименование родителя переименовывает и его
canon-наряды с вариациями (сначала спросим); удаление родителя удаляет их
тоже — в подтверждении указано количество. В Builder список Who содержит
только родителей; если у выбранного персонажа есть активные вариации,
появляется строка «Variant:» (default = сам родитель) — и в Standard, и
в Custom-шаблонах. В слотах Standard каждая кнопка 👁 показывает то, что
выбрано в её списке: у Who — персонажа, у Variant — выбранную вариацию. В Custom-шаблоне [Name n] остаётся именем родителя, а
[Description n] берётся из выбранной вариации. Неактивный родитель скрывает
свои вариации в Builder. Важно: старая сборка PromptForge на тех же данных
покажет вариации как обычных персонажей и при сохранении может потерять
их подпись и связь.

Каждая запись может содержать: референсное изображение (перетащите файл или
кликните Browse), URL источника (для кредита или переадресации оригинальной модели)
и привязанный LoRA (см. "LoRA Manager" ниже, что это делает).

Каждая запись и каждая папка также имеют состояние Active/Inactive, независимо
от всего вышеперечисленного. Неактивные записи и неактивные папки полностью
пропускаются выпадающими списками Builder — не просто показываются серым, а
реально не индексируются — так что вы можете отключить пачку
персонажей/стилей/outfits, которые сейчас не нужны, не удаляя их. Собственный
просмотр вкладки Library всё равно показывает неактивные записи (затемнённые,
отсортированные после активных в той же папке) — только Builder их реально
исключает. Кликните правой кнопкой на записи или папке для "Mark
Inactive"/"Mark Active" (работает и на множественном выделении), либо
используйте кнопки "Inactive All"/"Active All" внизу списка — обе меняют
подпись на количество и работают с вашим выделением, если оно есть, либо со
всей библиотекой, если ничего не выделено.

Запись также может нести видео-вложение рядом с референсным изображением —
полезно для записи из Image Actions/Video Actions (см. "Image Edit & Img2Video"
ниже), где "референс" сам по себе — короткий клип, а не кадр. Оно
воспроизводится через тот же встроенный плеер, что используется везде в
приложении, где показывается видео."""),

        "tools_category": ("Категория Tools", """\
Tools — это записи библиотеки, которые обычно НЕ имеют реального текста промпта —
их единственная причина существования — привязанный LoRA (фиксер анатомии, детализер
рук, LoRA резкости, или что-то, что Stable Diffusion не может сделать без него).
В отличие от всех остальных категорий, Tool можно сохранить совсем без тегов.

Если Tool ВСЕ ЖЕ имеет короткий тег (например, "@fixedanatomy"), вы можете отметить
"Force this tool's tag to the very start of the prompt" в редакторе Library — тогда
этот тег будет всегда в самом начале собранного промпта, перед Style/Characters/Scenario,
независимо от того, как вы переупорядочили всё остальное через "Block order...".
Tools без этого флага просто стоят там, где "Tools" находится в вашем блоке, как
любая другая секция.

Tools находится в выдвижной панели у правого края Builder (кликните
вкладку "»" чтобы открыть её) рядом с Seed и Resolution — и, как и
остальная часть этой панели, появляется только после подключения
ComfyUI."""),

        "lora_manager": ("Менеджер LoRA", """\
Каждый активный Style, Character, Outfit и Tool, у которого есть привязанный LoRA
в Library, автоматически попадает в LoRA Manager, помеченный [A] (automatic).
Вы также можете добавить LoRA вручную через "+ Add LoRA", помеченный [M] (manual) —
полезно для одноразового LoRA, который вы не хотите постоянно привязывать к записи.

LoRA имеет собственную страницу в сайдбаре ("⚙️ LoRA") вместо того чтобы
находиться внутри Builder — откройте её в любой момент, чтобы увидеть или
изменить каждый активный слот, не покидая эту страницу ради работы с
Characters/Scenario. Ваши слоты и силы сохраняются между сеансами.

Перед каждым "🎨 Generate in ComfyUI" имя каждого активного LoRA проверяется
против живого списка LoRA в ComfyUI — недостающий файл будет поймана прямо здесь,
перед отправкой, вместо того чтобы молча пропуститься во время генерации."""),

        "comfyui": ("Подключение к ComfyUI", """\
Прямая генерация совсем опциональна — "⚡ Generate prompt and copy" всегда работает
без настройки ComfyUI. Подключение разблокирует "🎨 Generate in ComfyUI" (отправьте
и смотрите генерацию, не покидая PromptForge), секцию Negative prompt, LoRA Manager
и очередь генерации.

Настройка: установите пакет PromptForge Connection custom node в ComfyUI/custom_nodes/,
поместите PromptForge Connector node куда-то в ваш ComfyUI граф, укажите
host/port на странице Settings (сайдбар), затем нажмите "Run" в футере
сайдбара, чтобы подключиться (кнопка станет "Disconnect" после подключения).

ВАЖНО — генерация ВСЕГДА нацелена на ПОСЛЕДНЮЮ АКТИВНУЮ вкладку workflow в браузере.
PromptForge не знает "какой workflow вы имели в виду": она просит bridge текущий
ComfyUI граф и отправляет туда. Если у вас открыто два workflow и вы кликнули на
другую вкладку просто чтобы взглянуть, ваша следующая генерация пойдёт ТУДА, LoRA
включены. Это верно даже если вы закроете вкладку, закроете браузер целиком или
убьёте процесс браузера — ComfyUI продолжит использовать последний активный workflow.
Это значит, что вы можете освободить оперативку вкладки браузера, как только подтвердили
нужный workflow, генерация при этом не пострадает.

Фреймы live preview полностью зависят от настройки ComfyUI Settings → Comfy →
Execution → Live preview method — если там "none", фреймы не придут, это не то,
что PromptForge контролирует."""),

        "queue": ("Очередь генерации", """\
Клик "🎨 Generate in ComfyUI" ВСЕГДА успешен сразу — он добавляет ваш текущий
промпт, seed, разрешение и снимок LoRA в очередь, вместо отказа если что-то уже
генерируется. ВСЁ про этот клик (включая какие LoRA и силы активны прямо сейчас)
замораживается в записи очереди — изменение силы LoRA потом влияет только на
БУДУЩИЕ клики, никогда на уже поставленное в очередь.

Только один job работает с ComfyUI в раз; предметы очереди ждут своей очереди
и стартуют автоматически как каждый закончится. "⏹ Stop" отменяет только текущий,
затем следующий в очереди стартует автоматически — он ничего не трогает в ожидании.
"🗑 Clear queue" удаляет всё ещё ОЖИДАЮЩЕЕ, но никогда текущий (совпадает как ComfyUI
собственный UI очереди ведёт себя) — используйте Stop для того конкретно.

Маленький "📋 N queued" счётчик рядом с Generate — это чтобы быстрая серия кликов
имела видимое подтверждение что они приземлились, вместо гадания приземлилось ли что-то."""),

        "history_gallery": ("История и Галерея", """\
Каждый промпт, который вы генерируете, автоматически сохраняется в History.
Картинка прикрепляется только если генерация реально шла через ComfyUI
("Generate in ComfyUI"); промпты, которые вы просто собрали и скопировали,
тоже остаются — но видны под фильтром "All" и без изображения.

Над списком два фильтра: "Generated Images" (по умолчанию) показывает только
записи с картинкой, "All" — все сохранённые промпты. Пропавший файл не удаляет
запись: превью пишет "Image file no longer available", и активной остаётся
только кнопка "Open folder". Если эта установка ещё ни разу не видела папку
output ComfyUI, превью пишет "Connect to ComfyUI to view this image"; после
первого подключения папка запоминается в настройках, поэтому картинки прошлых
сессий обычно видны сразу после перезапуска.

Выбор записи показывает превью изображения (или видео), текст промпта и — если
эти данные есть — три карточки с деталями под ним: LoRA (имя и сила для каждой),
Generation (разрешение, seed, шаги) и Negative prompt, плюс кнопки "Open image"
и "Open folder", использующие ту же логику "последняя известная ссылка", что и
лупа в Галерее. У каждого копируемого значения есть маленькая кнопка с
буфером обмена: промпт, каждая строка LoRA, Resolution, Seed и весь Negative
prompt. У Steps её намеренно нет (это значение негде повторно использовать).
Клик кладёт в буфер обмена ровно это значение и на мгновение показывает галочку.

Вкладка Gallery показывает каждое изображение И видео, сгенерированные через
ComfyUI В ЭТОМ сеансе, как thumbnail — наведитесь чтобы показать его в файловом
менеджере, кликните чтобы открыть полноразмерно. У видео автоматически
генерируется poster-frame thumbnail, чтобы оно не выглядело сломанной картинкой
рядом с настоящими, а клик открывает его в том же встроенном плеере, что
используется везде в приложении, где показывается видео (см. "Image Edit &
Img2Video" выше) — не в проигрывателе видео вашей ОС по умолчанию."""),

        "settings": ("Настройки", """\
Страница Settings (сайдбар) — это место, где находятся host/port ComfyUI —
раньше это жило внутри вкладки Builder, теперь переехало сюда. Здесь же
настраиваются тема (Dark, Light или полностью кастомная палитра), звуки
уведомлений и сборка промпта — см. "Sounds & Custom Themes" ниже, что именно
делают опция Custom-темы и карточка Sounds.

**Обёртка для нескольких персонажей.** Карточка Prompt assembly добавляет
необязательную обёртку для шаблона Standard; по умолчанию она выключена.
Если выбрано два персонажа или больше, теги и outfit каждого персонажа можно
заключить в собственную пару — круглую `( … )`, квадратную `[ … ]`,
вертикальные черты `| … |` или любые свои prefix/suffix. Точка остаётся снаружи
пары, поэтому промпт выглядит как `First: (tags, outfit).` Один персонаж
никогда не оборачивается, а Custom-шаблоны не затрагиваются. Это меняет только
группировку текста. Для Custom нужны и prefix, и suffix: если хотя бы одно
поле пустое, обёртка остаётся выключенной."""),

        "pipeline_modes": ("Image Edit & Img2Video (pipeline modes)", """\
Builder — это не только сборка изображения с нуля. Небольшой переключатель
режимов под иконкой ⚡ Builder в сайдбаре циклически переключает три режима
pipeline — T2I (Text → Image, по умолчанию), I2I (Image → Image) и I2V
(Image → Video) — и этот переключатель работает из любой вкладки приложения,
а не только пока открыт Builder; переключение режима, пока открыта Library,
например, сразу сужает панель категорий Library под новый режим, без
необходимости сначала переходить в Builder.

И I2I, и I2V требуют одной дополнительной разовой настройки в ComfyUI, помимо
Connector node из "Connecting to ComfyUI" выше: node **PromptForgeImageInput**,
подключенная в ваш i2i/i2v граф так же, как вы уже подключаете Connector или
Multi LoRA Loader. Именно она позволяет PromptForge отправлять входное
изображение в ComfyUI прямо из своего интерфейса — вам никогда не нужно
переключаться в браузер и использовать собственный виджет LoadImage ComfyUI.

Переключение в I2I или I2V заменяет привычную колонку Style/Characters/Scenario
на зону перетаскивания входного изображения сверху — перетащите файл или
кликните Browse — за которой следует секция Actions. Actions — это записи
библиотеки из новых категорий Image Actions / Video Actions (плюс любые
Custom-шаблоны, которые вы создали специально для i2i/i2v) — думайте о них как
об эквиваленте Style/Scenario для i2i/i2v: готовый текст промпта для
редактирования существующего изображения, а не описания нового с нуля. Tools
по-прежнему работают так же, как в T2I, в той же выдвижной панели.

Генерации в режиме I2V становятся в очередь и выполняются точно так же, как
генерации изображений (см. "Очередь генерации" ниже) — просто занимают больше
времени и производят видео вместо PNG. Результаты воспроизводятся через общий
встроенный видео-плеер везде, где они появляются — в панели результата
Builder, в History и на вкладке Gallery, которая также автоматически создаёт
poster-frame thumbnail для каждого видео, чтобы оно не выглядело сломанным
рядом с thumbnail-ами изображений."""),

        "sounds_and_themes": ("Sounds & Custom Themes", """\
Обе эти настройки живут на той же странице Settings (сайдбар), что и
подключение ComfyUI, каждая в своей карточке.

**Тема.** Помимо исходного переключателя Dark/Light теперь есть третий
вариант, Custom — два color picker'а (Base, Accent) плюс переключатель того,
должна ли Custom-тема тяготеть к светлому или тёмному концу производной
палитры. Каждая роль в приложении (карточки, границы, оба состояния кнопок,
title bar) выводится из этих двух цветов и обновляется вживую по мере
движения picker'ов, с автоматическим подбором контрастного цвета текста —
так что даже намеренно неудачная комбинация (очень светлый base + очень
светлый accent) остаётся читаемой. Вы также можете загрузить фоновое
изображение для Custom-темы, с выбором fit-mode и опциональным ползунком
прозрачности — карточки и панели сохраняют свои собственные сплошные фоны
поверх него, так что автоматической защиты читаемости нет; это осознанное
решение, а не баг, если яркое изображение делает какой-то угол хуже читаемым
при низкой непрозрачности.

**Звуки.** Три независимо настраиваемых звука уведомлений — "gen_ready"
(генерация завершена, превью-изображение готово к просмотру), "image_saved"
(срабатывает сегодня одновременно с gen_ready, но оставлен отдельной настройкой
на случай, если это когда-нибудь изменится) и "entry_added" (что-то сохранено
в History или в Library). Каждый по умолчанию None (тишина) и может быть
установлен на Default (короткий встроенный сигнал) или на любое количество
ваших собственных загруженных звуков, только WAV — файловый диалог даже не
предложит другие форматы, поскольку надёжное воспроизведение сжатого аудио
нельзя гарантировать на каждой машине. Добавьте звук через строку "+ Add
Sound…" в выпадающем списке; удалите через маленький "✕", который появляется
рядом с именем внутри открытого списка — выбирать его сначала не нужно.
У каждого звука свой ползунок громкости, отключённый, когда для этого действия
выбрано None. Если файл кастомного звука когда-либо пропадёт с диска
(перемещён или удалён вне PromptForge), соответствующее действие тихо
откатится на None при следующем запуске приложения, с одноразовым уведомлением
о том, что именно изменилось — никогда не тихий сбой в момент генерации."""),
    },
    "zh": {
        "quick_start": ("快速开始", """\
欢迎！这是第一次用你没有自己构建的库打开 PromptForge 时实际需要发生的顺序。

1. 转到 Library 标签页。点击左上角的 Styles、Characters、Outfits、Scenarios 和 Tools，
   并查看几个条目 — 只是为了在做任何其他事情之前感受一下这个库中实际包含的内容。
   如果一切都是空的，说明你还没有将 PromptForge 指向填充有内容的 prompt_forge_data/ 
   文件夹（或者你是从头开始的 — 见下面的"Library & Subfolders"了解条目如何工作）。

2. 转到 Builder 标签页。选择一个 Style，添加至少一个 Character（以及他们的 Outfit），
   可选地添加一个 Scenario。点击"⚡ Generate prompt and copy" — 这无需任何设置、
   不需要 ComfyUI，只是生成可以粘贴到任何地方的文本。

3. 如果你想让 PromptForge 直接为你生成图像（而不是粘贴提示词到别处），
   请参阅下面的"Connecting to ComfyUI" — 这是一个单独的、可选的步骤，有自己的一次性设置。

4. （可选，仅当你为这个库下载了 LoRA 文件时）一旦 ComfyUI 连接，
   返回 Library 标签页并点击"🔍 Check LoRA dependencies"以确认库期望的每个 LoRA 
   实际上都在 ComfyUI 能找到的地方。这可以在你开始生成数十个角色之前捕捉到
   "我真的下载了所有东西吗？"的问题，而不是之后在某个结果上看到混乱。

5. 如果你想从一张已有的图像开始，而不是空白的提示词 — 编辑它，或者把它
   变成一段短视频 — 见下面的"Image Edit & Img2Video (pipeline modes)"。
   这是一个从侧边栏切换进入的模式，不需要提前配置什么（除了该节里提到的
   一个一次性的 ComfyUI 节点）。

这就是整个循环。本指南中的其他一切都是其中某一部分的细节。"""),

        "library": ("库和子文件夹", """\
Library 标签页包含所有可重用的内容：Styles、Characters、Outfits、Scenarios 和 Tools。
每个条目只是一个名称加上一些文本（其"标签"）— Builder 将该文本粘贴到最终提示词中的任何位置。

子文件夹纯粹用于浏览。将条目拖到文件夹中，或将你的库组织成"Anime & Cartoon"/"Casual Clothes"等，
对搜索、Builder 的下拉菜单或 LoRA 的绑定没有任何影响 — 条目的名称仍然是在应用的其他地方
标识它的唯一东西。右键单击列表中的任何位置以获取文件夹选项（New folder、Move to...、
rename、delete）— 右键单击空白处仍然提供"New folder"，但不提供"Move to..."（没有选中任何东西来移动）。

Canonical Outfits 是一个特殊的、自动管理的文件夹：你标记为角色"canon"外观的服装会自动
被归档在那里，你无法手动将普通服装拖入其中。

Canon 服装还可以有一个可选的显示别名：在其卡片的 Name 字段中输入例如
"Office Suit"，然后点击 Save。别名只是给人看的标签 — 它永远不会重命名文件，
不会改变真正的 "Character_Canon_N" 键，也不会出现在提示词文本中。Library
列表会在真实名称后显示它（"Character — Canon 1 | Office Suit"），而
Builder 的服装选择器显示别名、内部仍保存 "Canon N" — 因此模板、History
和生成仍然能找到同一个文件。搜索会同时匹配两者。取消勾选 "canon" 只会隐藏
别名而不会删除它；重新勾选会恢复。Duplicate 创建的副本不带别名。新建 canon 服装的真实名称 "Character_Canon_N" 会在
Save 时自动分配；Library 编辑器不会显示它。

角色变体：一个角色可以有变体——例如 "human" 和 "fox-human" 这类不想拆成独立角色的
不同形态。选中已保存的角色，在其 Variations 卡片中点击 "Add variation…"。变体是该角色
已保存文本的副本：之后修改父角色不会改变已存在的变体。Library 列表中变体显示为父角色下的
子行（不能单独拖动，移动父角色时会一起移动）。变体的 Name 字段就是它的标签（在 Builder 中
显示）；真实文件名 "<Parent>__V<n>" 不会改变。Canon 服装与父角色共用。绑定到变体的 LoRA
会替换父角色的；没有绑定时使用父角色的。重命名父角色会同时重命名其 canon 服装和变体
（会先询问）；删除父角色也会一并删除它们，确认框会显示数量。在 Builder 中，Who 列表只显示
父角色；当所选角色有启用的变体时，会出现 "Variant:" 行（default = 父角色本身），Standard 和
Custom 模板都适用。在 Standard 槽位中，每个 👁 按钮预览各自下拉框所选内容：
Who 旁边预览角色，Variant 旁边预览所选变体。在 Custom 模板中 [Name n] 仍是父角色名称，[Description n] 使用所选变体。
被停用的父角色会让其变体在 Builder 中不可选。注意：旧版 PromptForge 打开同一份数据时会把
变体当作普通角色，保存时可能丢失其标签和关联。

每个条目可以选择包含：参考图像（将文件拖到编辑器上，或单击浏览）、源 URL
（用于指定或重定位原始模型）以及绑定的 LoRA（见下面的"LoRA Manager"了解它实际上做什么）。

每个条目和每个文件夹还带有 Active/Inactive 状态，独立于上面的一切。非活动条目和
非活动文件夹会被 Builder 的下拉菜单完全跳过 — 不只是显示为灰色，而是真的不被索引 —
所以你可以在不删除的情况下关闭一批暂时不需要的角色/风格/服装。Library 标签页自己的
浏览仍然显示非活动条目（变暗，排在同一文件夹内活动条目之后）— 只有 Builder 才会真正
排除它们。右键单击条目或文件夹选择"Mark Inactive"/"Mark Active"（对多选也有效），
或使用列表底部的"Inactive All"/"Active All"按钮 — 两者在有选中内容时会显示数量并只
作用于选中项，在没有选中内容时作用于整个库。

条目还可以在参考图像之外携带一个视频附件 — 对来自 Image Actions/Video Actions 的
条目（见下面的"Image Edit & Img2Video"）很有用，那里的"参考"本身就是一段短片而不是
静态图。它通过应用中显示视频的其他地方所用的同一个内嵌播放器播放。"""),

        "tools_category": ("Tools 类别", """\
Tools 是库条目，通常没有真正的提示词文本 — 它们存在的唯一原因是绑定的 LoRA
（解剖学修复器、手部细节器、锐度 LoRA，任何 Stable Diffusion 实际上无法做到的事情）。
与其他每个类别不同，Tool 可以以完全空的标签保存。

如果 Tool 确实有一个简短的标签（某些工作流用"@fixedanatomy"之类的东西触发特定的 LoRA 行为），
你可以在 Library 编辑器中标记它"Force this tool's tag to the very start of the prompt" —
该标签随后总是会在组装的提示词的最开始，在 Style/Characters/Scenario 之前，无论你如何通过
"Block order..."重新排序其他所有内容。没有该标志的 Tools 只是坐在你的块顺序中"Tools"落在的地方，
就像任何其他部分一样。

Tools 位于 Builder 右侧边缘的滑出面板中（点击"»"标签打开它），
与 Seed 和 Resolution 在一起 — 和该面板的其余部分一样，
只有在连接 ComfyUI 后才会出现。"""),

        "lora_manager": ("LoRA 管理器", """\
Library 中每个绑定了 LoRA 的活跃 Style、Character、Outfit 和 Tool 都自动进入 LoRA 管理器，
标记为 [A]（自动）。你也可以用"+ Add LoRA"手动添加 LoRA，标记为 [M]（手动）—
对于你不想永久绑定到库条目的一次性 LoRA 很有用。

LoRA 现在拥有自己独立的侧边栏页面（"⚙️ LoRA"），而不再位于 Builder 内部 —
随时打开它即可查看或调整每个活跃插槽，无需离开该页面去处理 Characters/Scenario。
你的插槽和强度在会话之间持续存在。

在每个"🎨 Generate in ComfyUI"之前，每个活跃插槽的 LoRA 名称都会针对 ComfyUI 自己的实时 LoRA 列表进行检查 —
缺失的文件在这里被捕捉，在提交之前，而不是在生成过程中被静默跳过。"""),

        "comfyui": ("连接到 ComfyUI", """\
直接生成完全是可选的 — "⚡ Generate prompt and copy"总是无需任何 ComfyUI 设置而工作。
连接解锁"🎨 Generate in ComfyUI"（提交并观看它生成，无需离开 PromptForge）、
Negative prompt 部分、LoRA 管理器和生成队列。

设置：将 PromptForge Connection 自定义节点包安装到 ComfyUI/custom_nodes/，
在 ComfyUI 图中的某处放置一个 PromptForge Connector 节点，在 Settings 页面
（侧边栏）中设置 host/port，然后点击侧边栏底部的"Run"按钮进行连接
（连接后按钮会变为"Disconnect"）。

重要 — 生成总是针对你浏览器中的最后活跃工作流标签页。PromptForge 没有"你指的是哪个工作流"的概念：
它向桥询问在浏览器中最近活跃的 ComfyUI 图，然后提交到那里。
如果你打开了两个工作流并点击到不同的标签页只是看一眼，你的下一个生成就会去那里，LoRA 包括在内。
即使你关闭浏览器标签页、完全关闭浏览器或在之后杀死浏览器进程，这也成立 —
ComfyUI 会继续使用最后活跃的工作流。这也意味着一旦你确认了正确的工作流处于活跃状态，
你可以释放浏览器标签页使用的 RAM，而不会影响生成。

实时预览帧完全取决于 ComfyUI 自己的 Settings → Comfy → Execution → Live preview method 设置 —
如果设置为"none"，就不会有帧到达，这不是 PromptForge 控制的东西。"""),

        "queue": ("生成队列", """\
点击"🎨 Generate in ComfyUI"总是立即成功 — 它将你当前的提示词、种子、分辨率和 LoRA 快照
添加到队列中，而不是在已有东西生成时拒绝。关于该点击的所有内容（包括哪些 LoRA 和强度在那时是活跃的）
都被冻结到该队列条目中 — 之后改变 LoRA 强度只影响未来的点击，永远不会影响已经排队的。

一次只有一个任务与 ComfyUI 一起运行；排队的项目等待轮到它们，并在每个完成时自动开始。
"⏹ Stop"只取消当前正在运行的，然后下一个排队项目自动开始 —
它永远不会触及仍在等待的任何东西。"🗑 Clear queue"删除仍然在等待中的所有内容，
但永远不是已经生成的那个（符合 ComfyUI 自己的内置队列 UI 的行为）—
为那个具体的使用 Stop。

"Generate"旁边的小"📋 N queued"计数器存在的目的是，快速的一连串点击有可见的确认他们实际上着陆了，
而不是想知道是否有什么发生。"""),

        "history_gallery": ("历史和画廊", """\
你生成的每个提示词都会自动保存到 History。只有实际通过 ComfyUI 运行的生成
（"Generate in ComfyUI"）才会附带图片；仅仅生成并复制提示词的条目也会保留，
但只在 "All" 下显示，且没有图片。

列表上方有两个筛选："Generated Images"（默认）只列出带图片的条目，
"All" 列出所有已保存的提示词。文件丢失不会删除条目 — 预览会显示
"Image file no longer available"，此时只有 "Open folder" 仍然可用。如果这个
安装还从未见过 ComfyUI 的输出文件夹，预览会显示
"Connect to ComfyUI to view this image"；连接成功一次后该文件夹会记在设置里，
所以重启后通常能直接看到之前会话的图片。

选中条目会显示图片（或视频）预览、提示词文本，以及（存在这些数据时的）下方
三张详情卡片：LoRA（每个使用项的 LoRA 名称和强度）、Generation（分辨率、
种子、步数）和 Negative prompt，还有 "Open image" 和 "Open folder" 按钮，
使用与 Gallery 放大镜相同的"最后已知链接"逻辑。每个可复制的值旁边都有一个小
剪贴板按钮：提示词、每行 LoRA、Resolution、Seed 和整个 Negative prompt。
Steps 有意不提供（没有可重复使用的场合）。点击按钮会把该值放入剪贴板，
并短暂显示一个对勾。

Gallery 标签页显示在此会话中通过 ComfyUI 生成的每个图像和视频作为缩略图 —
悬停以在文件浏览器中显示它，点击以全尺寸打开它。视频会自动生成 poster-frame
缩略图，这样它就不会看起来像是坏掉的图片一样夹在真正的图片之间；点击视频会用
应用中显示视频的其他地方所使用的同一个内嵌播放器打开它（见上面的"Image Edit &
Img2Video"），而不是你系统默认的视频播放器。"""),

        "settings": ("设置", """\
Settings 页面（侧边栏）是 ComfyUI 的 host/port 所在的位置 — 以前位于 Builder
标签页内部，现在搬到了这里。主题（Dark、Light 或完全自定义的调色板）、通知
音效以及提示词组装也在这里配置 — 见下面的"Sounds & Custom Themes"了解 Custom
主题选项和 Sounds 卡片具体做什么。

**多角色包裹。** Prompt assembly 卡片为 Standard 模板提供一个可选的包裹功能，
默认关闭。选择两个或更多角色时，每个角色的 tags 和 outfit 都可以各自用一对
符号包起来 — 圆括号 `( … )`、方括号 `[ … ]`、竖线 `| … |`，或者你输入的自定义
前缀/后缀。句号保留在符号对之外，所以提示词形如 `First: (tags, outfit).`
单个角色永远不会被包裹，Custom 模板也不受影响。它只改变文本的分组方式。
选择 Custom 时必须同时填写前缀和后缀；任意一边为空，包裹就保持关闭。"""),

        "pipeline_modes": ("Image Edit & Img2Video (pipeline modes)", """\
Builder 不只是用来从零开始搭建图像的。侧边栏 ⚡ Builder 图标下方的一个小模式
切换器在三种 pipeline 模式之间循环切换 — T2I（Text → Image，默认）、I2I
（Image → Image）和 I2V（Image → Video）— 这个控件在应用的任何标签页都能用，
不仅限于 Builder 打开时；比如在 Library 打开的情况下切换模式，会立即让 Library
的分类栏跟着变窄，而不需要先切回 Builder。

I2I 和 I2V 都需要在上面"Connecting to ComfyUI"提到的 Connector 节点之外，
再做一次一次性的 ComfyUI 设置：把 **PromptForgeImageInput** 节点接入你的
i2i/i2v 工作流图，方式和你接入 Connector 或 Multi LoRA Loader 完全一样。正是
这个节点让 PromptForge 能够直接从自己的界面把输入图像推送到 ComfyUI — 你永远
不需要切换到浏览器去用 ComfyUI 自己的 LoadImage 控件。

切换到 I2I 或 I2V 会把平时的 Style/Characters/Scenario 那一栏换成顶部的输入
图像拖放区 — 把文件拖上去，或点击浏览 — 后面跟着一个 Actions 区块。Actions
是来自新的 Image Actions / Video Actions 分类的库条目（加上你专门为 i2i/i2v
建的任何 Custom 模板）— 可以把它们看作 i2i/i2v 版本的 Style/Scenario：为编辑
已有图像准备的现成提示词，而不是从零描述一张新图。Tools 的用法和 T2I 中完全
一样，还是在同一个滑出面板里。

I2V 模式下的生成排队和运行方式与图像生成完全相同（见下面的"生成队列"）—
只是耗时更长，产出的是视频而不是 PNG。结果会通过一个共享的内嵌视频播放器
播放，出现在任何地方 — Builder 的结果面板、History，以及 Gallery 标签页，
后者还会为每个视频自动生成 poster-frame 缩略图，这样它就不会在图片缩略图旁边
显得像是坏掉了。"""),

        "sounds_and_themes": ("Sounds & Custom Themes", """\
这两项设置都位于和 ComfyUI 连接同一个 Settings 页面（侧边栏），各自有自己的
卡片。

**主题。** 除了原有的 Dark/Light 切换之外，现在多了第三个选项 Custom —
两个取色器（Base、Accent）加上一个切换开关，决定 Custom 主题应该偏向派生
调色板的浅色端还是深色端。应用中的每一个角色（卡片、边框、两种按钮状态、
title bar）都由这两个颜色派生而来，并随着你拖动取色器实时更新，还会自动选择
对比度安全的文字颜色，所以即便是刻意选一个别扭的组合（非常浅的 base + 非常浅
的 accent）也依然可读。你还可以为 Custom 主题上传一张背景图，带有 fit-mode
选择和可选的透明度滑块 — 卡片和面板会在它上面保留自己的纯色背景，所以没有
自动的可读性保护；如果一张花哨的图片在低透明度下让某个角落变得难读，这是
刻意的设计选择，不是 bug。

**音效。** 三个可独立配置的通知音效 — "gen_ready"（一次生成完成，预览图已经
可以查看了）、"image_saved"（目前和 gen_ready 同时触发，但作为单独的设置保留，
以备将来两者分开）和 "entry_added"（有东西被保存到了 History 或 Library）。
每一个默认都是 None（静音），可以设为 Default（一个简短的内置提示音）或任意
数量你自己上传的音效，仅限 WAV — 文件选择对话框甚至不会提供其他格式，因为
压缩音频在不同机器上能否可靠播放是无法保证的。通过下拉菜单里的"+ Add
Sound…"一行添加音效；通过打开的下拉列表中名称旁出现的小"✕"删除，不需要先
选中它。每个音效都有自己的音量滑块，当该动作设为 None 时禁用。如果某个自定义
音效文件在磁盘上丢失（在 PromptForge 之外被移动或删除），对应的动作会在下次
启动应用时悄悄回退到 None，并弹出一次性提示告诉你具体哪个变了 — 绝不会在生成
时悄无声息地失败。"""),
    },
    "ja": {
        "quick_start": ("クイックスタート", """\
ようこそ！これは、自分で構築していないライブラリで初めて PromptForge を開くときに
実際に起こる必要がある順序です。

1. Library タブに移動します。左上の Styles、Characters、Outfits、Scenarios、
   Tools をクリックして、いくつかのエントリを見てください — 何か他にすることの前に、
   このライブラリに実際に何が含まれているかを感じるためだけです。
   すべてが空の場合、PromptForge をまだ populate された prompt_forge_data/ 
   フォルダに指していないか（またはゼロから開始しています — 
   エントリがどのように機能するかについては下の「Library & Subfolders」を参照）。

2. Builder タブに移動します。Style を選択し、少なくとも 1 つの Character（および彼らの Outfit）を追加し、
   オプションで Scenario を追加します。「⚡ Generate prompt and copy」をクリックします — 
   これはセットアップなしで、ComfyUI は不要で、単にどこにでも貼り付けられるテキストを生成します。

3. PromptForge に直接イメージを生成させたい場合（プロンプトを他の場所に貼り付ける代わりに）、
   下の「Connecting to ComfyUI」を参照してください — これは別の、オプションのステップで、
   独自の 1 回限りのセットアップがあります。

4. （オプション、このライブラリ用に LoRA ファイルをダウンロードした場合のみ）
   ComfyUI が接続されたら、Library タブに戻り、「🔍 Check LoRA dependencies」をクリックして、
   ライブラリが期待するすべての LoRA が ComfyUI が見つけられる場所に実際にあることを確認します。
   これは数十のキャラクターを生成し始めた後ではなく、その前に「本当にすべてをダウンロードしたか？」
   をキャッチします。

5. 空のプロンプトではなく、すでにある画像から始めたい場合 — 編集する、あるいは
   短い動画に変換する場合 — は下の「Image Edit & Img2Video (pipeline modes)」を
   参照してください。これはサイドバーから切り替えるモードで、事前に何かを設定して
   おく必要はありません（そのセクションで説明する、1 回限りの ComfyUI ノードを除いて）。

これが全体のループです。このガイドの他のすべては、その一部の細節です。"""),

        "library": ("ライブラリとサブフォルダ", """\
Library タブには、すべての再利用可能なもの、つまり Styles、Characters、Outfits、
Scenarios、Tools が含まれています。各エントリは単なる名前とテキスト（「タグ」）です — 
Builder はそのテキストを最終プロンプトにあなたがそのエントリを配置する場所に貼り付けます。

サブフォルダは閲覧専用です。エントリをフォルダにドラッグしたり、ライブラリを
「Anime & Cartoon」/「Casual Clothes」などに整理したりすることは、検索、Builder の
ドロップダウン、または LoRA がバインドされている内容に一切影響しません — エントリの
名前は、アプリ全体で他の場所で識別される唯一のものです。
リストのどこかを右クリックしてフォルダオプション（New folder、Move to...、
rename、delete）を取得します — 空白をクリックすると「New folder」が提供されますが、
「Move to...」は提供されません（移動するものが選択されていません）。

Canonical Outfits は特殊な、自動管理フォルダです。キャラクターの「canonical」ルックアスとしてマークした
衣装は自動的にそこに提出され、普通の衣装を手動でそこにドラッグすることはできません。

Canon 衣装には任意の表示エイリアスを付けられます — カードの Name 欄に
「Office Suit」のようなラベルを入力して Save するだけです。エイリアスは
人間向けのラベルにすぎません。ファイル名を変更せず、実際の
「Character_Canon_N」キーを変えず、プロンプト本文にも入りません。
Library の一覧では実際の名前の後に表示され（「Character — Canon 1 |
Office Suit」）、Builder の衣装セレクタではエイリアスを表示しつつ内部では
「Canon N」を保持するため、テンプレート、History、生成は同じファイルを
解決し続けます。検索は両方に一致します。「canon」のチェックを外すと
エイリアスは削除されず非表示になるだけです。再度チェックすると戻ります。
Duplicate で作られるコピーにはエイリアスは付きません。新しい canon 衣装の実名
「Character_Canon_N」は Save 時に自動で付与され、Library エディタには表示されません。

キャラクターのバリエーション：キャラクターには「human」「fox-human」のような別の姿を
バリエーションとして持たせられます（別キャラクターにしたくない場合に便利です）。保存済みの
キャラクターを選び、Variations カードの「Add variation…」を押します。バリエーションは保存済み
テキストのコピーです：後から親を編集しても、既存のバリエーションは変わりません。Library の
一覧ではバリエーションは親の下の子行として表示されます（単独ではドラッグできず、親を移動すると
一緒に動きます）。バリエーションの Name 欄はラベル（Builder に表示）で、実ファイル名
「<Parent>__V<n>」は変わりません。Canon 衣装は親と共有します。バリエーションに紐づけた LoRA は
親の LoRA を置き換え、未設定なら親のものを使います。親の名前を変えると canon 衣装とバリエーションも
一緒に改名され（事前に確認）、親を削除するとそれらも削除されます（確認に件数が出ます）。
Builder の Who には親キャラクターだけが並び、有効なバリエーションがあるときは「Variant:」行
（default = 親自身）が現れます（Standard と Custom の両方）。Standard のスロットでは、
各 👁 ボタンがそれぞれのドロップダウンの内容を表示します：Who の横はキャラクター、
Variant の横は選択中のバリエーションです。Custom テンプレートでは [Name n] は
親の名前のまま、[Description n] は選んだバリエーションを使います。非アクティブな親のバリエーションは
Builder で選べません。注意：古い PromptForge で同じデータを開くとバリエーションは通常の
キャラクターとして見え、保存時にラベルやリンクが失われることがあります。

各エントリはオプションで次のものを含めることができます：参照画像
（編集者にファイルをドラッグするか、参照をクリックします）、
ソース URL（元のモデルをクレジットまたはリダイレクトするため）、
およびバインドされた LoRA（それが実際に何をするかについては下の「LoRA Manager」参照）。

各エントリと各フォルダは、上記とは独立に Active/Inactive 状態も持っています。
非アクティブなエントリと非アクティブなフォルダは Builder のドロップダウンから
完全に除外されます — 単にグレー表示になるだけでなく、実際にインデックスされ
なくなります — そのため、今は必要ないキャラクター/スタイル/衣装のまとまりを
削除せずにオフにできます。Library タブ自体のブラウジングでは非アクティブな
エントリも表示されます（薄く表示され、同じフォルダ内のアクティブなエントリの
後に並びます）— それらを実際に除外するのは Builder だけです。エントリや
フォルダを右クリックして「Mark Inactive」/「Mark Active」を選択できます
（複数選択にも対応）。またはリスト下部の「Inactive All」/「Active All」
ボタンを使うこともできます — どちらも選択があればその件数を表示して選択に
対してのみ、選択がなければライブラリ全体に対して動作します。

エントリは参照画像とは別に、動画添付ファイルも持てます — Image
Actions/Video Actions（下の「Image Edit & Img2Video」参照）のエントリで、
「参照」自体が静止画ではなく短いクリップである場合に便利です。アプリ内で
動画が表示される他の場所と同じ、共有の埋め込みプレーヤーで再生されます。"""),

        "tools_category": ("Tools カテゴリー", """\
Tools は通常、実際のプロンプトテキストを持たないライブラリエントリです — それが存在する唯一の理由は
バインドされた LoRA（解剖学フィクサー、手詳細記述子、シャープネス LoRA、
Stable Diffusion が実際に行うことができないもの）です。他のすべてのカテゴリーとは異なり、
Tool は完全に空のタグで保存できます。

Tool が実際に短いタグを持つ場合（一部のワークフローは「@fixedanatomy」のような
特定の LoRA 動作をトリガーします）、Library エディターで
「Force this tool's tag to the very start of the prompt」をマークできます — 
そのタグはその後、「Block order...」で他のすべてを再度配列する方法に関係なく、
組み立てられたプロンプトの最初に、Style/Characters/Scenario の前に常に出現します。
そのフラグなしの Tools は、他のセクション同様に、ブロック順で「Tools」が落ちる場所に座ります。

Tools は Builder の右端にあるスライドアウトパネル内にあります
（「»」タブをクリックして開きます）。Seed や Resolution と同じ場所にあり、
このパネルの他の部分と同様、ComfyUI に接続した後にのみ表示されます。"""),

        "lora_manager": ("LoRA マネージャー", """\
Library で LoRA がバインドされたすべてのアクティブな Style、Character、Outfit、および Tool は
自動的に LoRA Manager に引き込まれ、[A]（自動）とタグされます。「+ Add LoRA」で
LoRA を手動で追加することもでき、[M]（手動）とタグされます — 
ライブラリエントリに永続的にバインドしたくない 1 回限りの LoRA に役立ちます。

LoRA は Builder の内部ではなく、サイドバーに独自のページ（「⚙️ LoRA」）を持っています —
Characters/Scenario の作業のためにそのページを離れることなく、いつでも開いて
各アクティブスロットを確認・調整できます。スロットと強度はセッション間で保持されます。

すべての「🎨 Generate in ComfyUI」の前に、すべてのアクティブスロットの LoRA 名は
ComfyUI 自体のライブ LoRA リストに対してチェックされます — 
生成中に静かにスキップされるのではなく、提出される前にここで欠落ファイルがキャッチされます。"""),

        "comfyui": ("ComfyUI への接続", """\
直接生成は完全にオプションです — 「⚡ Generate prompt and copy」は常に ComfyUI セットアップなしで動作します。
接続すると、「🎨 Generate in ComfyUI」（送信して PromptForge を離さずに生成を見ます）、
Negative prompt セクション、LoRA Manager、および生成キューがアンロックされます。

セットアップ：PromptForge Connection カスタムノードパッケージを ComfyUI/custom_nodes/ にインストールし、
ComfyUI グラフの どこかに PromptForge Connector ノードを配置し、
Settings ページ（サイドバー）で host/port を設定してから、
サイドバー下部の「Run」ボタンをクリックして接続します
（接続すると「Disconnect」に変わります）。

重要 — 生成は常にブラウザーで最後にアクティブなワークフロータブをターゲットにします。
PromptForge には「どのワークフローを意味したか」の概念がありません。
ブリッジにブラウザーで最近アクティブだった ComfyUI グラフを質問し、そこに送信します。
2 つのワークフローが開かれており、一見するためだけに別のタブをクリックした場合、
次の生成はそこに行き、LoRA が含まれます。これは、ブラウザータブを閉じたり、
ブラウザーを完全に閉じたり、その後ブラウザープロセスを強制終了した場合でも適用されます — 
ComfyUI は最後にアクティブなワークフローを使い続けます。
これはまた、正しいワークフローがアクティブであることを確認したら、ブラウザータブが使用する RAM を
解放でき、生成に影響を与えないことを意味します。

ライブプレビューフレームは、ComfyUI 自体の Settings → Comfy → Execution → 
Live preview method 設定に完全に依存しています — 「none」に設定されている場合、
フレームは到着せず、これは PromptForge が制御していません。"""),

        "queue": ("生成キュー", """\
「🎨 Generate in ComfyUI」をクリックすると、常に直ちに成功します — 
現在のプロンプト、シード、解像度、および LoRA スナップショットをキューに追加します。
何か生成中の場合は拒否せず、キューに追加します。
そのクリックに関するすべてのもの（どの LoRA と強度がその時点でアクティブか含む）
がキューエントリに固定されます — その後に LoRA 強度を変更すると、
既にキューに入れられたもの、決して将来のクリックのみが影響を受けます。

一度に ComfyUI で正確に 1 つのジョブが実行されます。
キューに入れられたアイテムは順番を待ち、各アイテムが完了すると自動的に開始されます。
「⏹ Stop」は現在実行中のもののみをキャンセルし、
次のキューに入れられたアイテムは自動的に開始されます — 待機中のものには一切触れません。
「🗑 Clear queue」は待機中のすべてを削除しますが、既に生成中のものは削除しません
（ComfyUI 自体の組み込みキュー UI がどのように動作するかと一致します）— 
その 1 つについては Stop を使用します。

「Generate」の横にある小さな「📋 N queued」カウンター は、
クリックの急速な一連が実際に着地したという可視確認があるためです。
何かが起こったかどうかを疑問に思うのではなく。"""),

        "history_gallery": ("履歴とギャラリー", """\
生成するすべてのプロンプトは自動的に History に保存されます。画像が添付される
のは、実際に ComfyUI 経由で生成した場合（「Generate in ComfyUI」）だけです。
組み立ててコピーしただけのプロンプトも残りますが、「All」でのみ表示され、
画像はありません。

リストの上には 2 つのフィルターがあります。「Generated Images」（既定）は画像の
あるエントリだけを、「All」は保存されたすべてのプロンプトを表示します。ファイルが
失われてもエントリは削除されません — プレビューに
「Image file no longer available」と表示され、「Open folder」だけが有効なままです。
このインストールがまだ ComfyUI の出力フォルダを認識していない場合は、代わりに
「Connect to ComfyUI to view this image」と表示されます。一度接続するとフォルダが
設定に記憶されるため、通常は再起動後すぐに以前のセッションの画像が表示されます。

エントリを選ぶと、画像（または動画）のプレビュー、プロンプト本文、そしてデータが
ある場合は下に 3 つの詳細カード — LoRA（使用した各 LoRA の名前と強度）、
Generation（解像度、シード、ステップ数）、Negative prompt — が表示されます。
さらに「Open image」「Open folder」ボタンがあり、Gallery の虫眼鏡と同じ
「最後の既知リンク」ロジックを使います。コピーできる値には小さなクリップボード
ボタンが付きます: プロンプト、各 LoRA 行、Resolution、Seed、Negative prompt 全体。
Steps には意図的にありません（再利用する場面がないため）。クリックするとその値が
クリップボードに入り、一瞬チェックマークが表示されます。

Gallery タブは、このセッションで ComfyUI を通じて生成されたすべての画像と動画を
サムネイルとして表示します — ホバーしてファイルエクスプローラーで表示し、
クリックしてフルサイズで開きます。動画には自動生成されたポスターフレームの
サムネイルが付くので、画像のサムネイルの隣で壊れているように見えることはありません。
クリックすると、アプリ内で動画が表示される他の場所と同じ埋め込みプレーヤーで
開きます（上の「Image Edit & Img2Video」参照）— OS 標準の動画プレーヤーでは
ありません。"""),

        "settings": ("設定", """\
Settings ページ（サイドバー）は、ComfyUI の host/port が置かれている場所です —
以前は Builder タブの内部にありましたが、現在はここに移動しています。テーマ
（Dark、Light、または完全にカスタムなパレット）、通知音、そしてプロンプトの
組み立てもここで設定します — Custom テーマオプションと Sounds カードが実際に
何をするかについては、下の「Sounds & Custom Themes」を参照してください。

**複数キャラクターのラッパー。** Prompt assembly カードは Standard テンプレート用の
任意のラッパーを追加します。初期状態はオフです。2 人以上のキャラクターを選ぶと、
各キャラクターの tags と outfit をそれぞれ独自のペアで囲めます — 丸括弧
`( … )`、角括弧 `[ … ]`、縦線 `| … |`、または自分で入力した任意のプレフィックス/
サフィックスです。句点はペアの外側に残るため、プロンプトは
`First: (tags, outfit).` のようになります。1 人だけの場合は決して囲まれず、
Custom テンプレートも影響を受けません。これはテキストのまとめ方だけを変える
ものです。Custom ではプレフィックスとサフィックスの両方が必要で、どちらかが
空ならラッパーはオフのままです。"""),

        "pipeline_modes": ("Image Edit & Img2Video (pipeline modes)", """\
Builder はゼロから画像を組み立てるためだけのものではありません。サイドバーの
⚡ Builder アイコンの下にある小さなモード切り替えは、3 つのパイプラインモード —
T2I（Text → Image、デフォルト）、I2I（Image → Image）、I2V（Image → Video）—
を順に切り替えます。この操作はアプリ内のどのタブからでも行えます。Builder が
開いているときだけではありません。たとえば Library を開いた状態でモードを
切り替えると、タブを切り替えなくても Library のカテゴリーバーがすぐに新しい
モードに合わせて絞り込まれます。

I2I と I2V はどちらも、上の「Connecting to ComfyUI」で説明した Connector
ノードに加えて、もう 1 つ 1 回限りの ComfyUI 設定が必要です：**
PromptForgeImageInput** ノードを、Connector や Multi LoRA Loader を配線する
のとまったく同じ方法で、あなたの i2i/i2v グラフに配線します。これにより、
PromptForge は自分自身の UI から入力画像を直接 ComfyUI に送り込めるように
なります — ブラウザに Alt-Tab で切り替えて ComfyUI 自体の LoadImage ウィジェット
を使う必要はもうありません。

I2I または I2V に切り替えると、通常の Style/Characters/Scenario の列が、
上部の入力画像用のドロップゾーンに置き換わります — ファイルをドラッグする
か、クリックして参照します — その下に Actions セクションが続きます。Actions
は、新しい Image Actions / Video Actions カテゴリー（に加えて、i2i/i2v 用に
あなたが作った Custom テンプレート）からのライブラリエントリです — 既存の
画像を編集するための、あらかじめ用意されたプロンプトテキストという意味で、
i2i/i2v 版の Style/Scenario だと考えてください。ゼロから新しい画像を説明する
ものではありません。Tools は T2I とまったく同じように、同じスライドアウト
パネルの中で機能します。

I2V モードでの生成は、画像生成とまったく同じ方法でキューに入り、実行されます
（下の「生成キュー」参照）— 時間がかかり、PNG の代わりに動画が生成される点が
違うだけです。結果は、共有の埋め込み動画プレーヤーで、それが表示される
あらゆる場所で再生されます — Builder の結果パネル、History、そして Gallery
タブ。Gallery タブはさらに、各動画について自動的にポスターフレームのサムネイル
を生成するので、画像のサムネイルの隣で壊れているように見えることはありません。"""),

        "sounds_and_themes": ("Sounds & Custom Themes", """\
どちらも、ComfyUI 接続と同じ Settings ページ（サイドバー）に、それぞれ専用の
カードとして存在します。

**テーマ。** もともとの Dark/Light 切り替えに加えて、今では 3 番目の選択肢
Custom があります — 2 つのカラーピッカー（Base、Accent）と、Custom が派生
パレットの明るい側と暗い側のどちらに寄るべきかを決めるトグルです。アプリ内の
あらゆる役割（カード、ボーダー、両方のボタン状態、title bar）はこの 2 つの
色から導出され、ピッカーを動かすたびにライブに更新されます。コントラストが
安全なテキスト色が自動的に選ばれるので、意図的に扱いにくい組み合わせ（非常に
明るい base + 非常に明るい accent）を選んでも読みやすさは保たれます。Custom
テーマ用に背景画像をアップロードすることもでき、フィットモードの選択と
オプションの不透明度スライダーが付いています — カードやパネルはその上でも
自分自身の単色背景を保持するので、自動的な可読性保護はありません。低い
不透明度で賑やかな画像がどこかの隅を読みにくくしてしまうとしても、それは
意図的な設計であり、バグではありません。

**サウンド。** 独立して設定できる 3 つの通知音 — 「gen_ready」（生成が完了し、
プレビュー画像が見られる状態になった）、「image_saved」（今のところ
gen_ready と同時に発火しますが、将来分かれる可能性に備えて別設定として
残されています）、「entry_added」（History または Library に何かが保存
された）。それぞれデフォルトは None（無音）で、Default（短い内蔵チャイム音）
または自分でアップロードした好きな数のサウンドに設定できます。WAV のみ対応 —
圧縮音声の再生が全てのマシンで確実に動くとは保証できないため、ファイル選択
ダイアログには他の形式は表示すらされません。ドロップダウンの「+ Add
Sound…」の行からサウンドを追加します。削除は、開いたドロップダウン内で
名前の横に表示される小さな「✕」から行います — 事前に選択しておく必要は
ありません。各サウンドには専用の音量スライダーがあり、そのアクションが
None に設定されているときは無効になります。カスタムサウンドのファイルが
ディスクから失われた場合（PromptForge の外で移動または削除された場合）、
該当のアクションは次回アプリ起動時に静かに None にフォールバックし、どれが
変更されたかを知らせる一度きりの通知が表示されます — 生成時に無言で
失敗することは決してありません。"""),
    },
}

for _lang in GUIDE_LANGUAGES:
    if _lang in ("en", "ru", "zh", "ja"):
        continue
    GUIDE_CONTENT[_lang] = {
        key: _guide_pending(_lang, title, body)
        for key, (title, body) in GUIDE_CONTENT["en"].items()
    }

# Section order for the guide's left-hand navigation list — GUIDE_CONTENT
# is keyed by language, but every language shares this same section order
# (a dict literal's insertion order isn't something to rely on after the
# placeholder-generation loop above runs, hence a separate explicit list).
GUIDE_SECTION_ORDER = [
    "quick_start", "library", "tools_category", "comfyui", "pipeline_modes",
    "lora_manager", "queue", "history_gallery", "settings", "sounds_and_themes",
]

