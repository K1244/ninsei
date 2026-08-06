> IMPLEMENTATION STATUS (updated 2026-08-06): backend domain model, access
> engine, and REST API for sections 4-9 are implemented and wired into
> main.py (see models.py, services/access_service.py + friends,
> routers/directory_router.py, routers/patron_router.py, the Clubowna
> sections of guest_router.py/venue_router.py). Demo data for section 12's
> five venues is in scripts/seed_demo.py (`python -m backend.scripts.seed_demo`).
> Section 7's venue-admin UI is now wired into dashboard.html/dashboard.js:
> venue identity + access mode + module toggles, event create/delete,
> membership-plan and product create/enable-disable/delete, and access-
> request approve/reject all work end-to-end from the existing dashboard.
> Not yet built: edit-in-place for events/plans/products (create+delete only
> for now), the pixelart room/game-scene frontend (sections 2, 3, 10 --
> nothing started, no game canvas/movement/hotspots).
>
> Art pipeline (section 17): the raw AI-generated reference sheets (15 PNGs
> -- avatar turnarounds, room furniture, event props, venue tiles) were cut
> into 405 individual transparent sprites by tools/slice_sprites.py, living
> in frontend/static/assets/sprites/{avatars,room,props,venue}/ with a
> manifest.json. config.py's AVATAR_OPTIONS/SCENE_PROP_SPRITES/
> SCENE_THEME_SOURCE_SHEETS index them; GET /api/users/avatar-options and
> PATCH /api/users/me (avatar field, now validated) are live.
>
> Sections 2/3/10 (pixelart frontend) are now built: /room is the landing
> scene (movable avatar via WASD/arrows or click-to-move, hotspots for
> bed/computer/poster/wardrobe/door, wardrobe opens the avatar picker);
> /venues is the hub (card grid off GET /api/venues); /venue/{slug} is the
> venue scene (themed floor + furniture + door state + event props +
> ambient crowd, all DOM/CSS-positioned per room.js's fixed-resolution-
> world pattern, no canvas/game-engine) with a CTA panel wired to every
> access-gated action (enter/jukebox, observe, request access, join a
> plan, buy a product, show QR pass). All three boot-tested end-to-end
> with Playwright (screenshots + click-throughs), not just imported.
>
> Not built yet: the QR *scanner* (staff-facing, section 8's other half),
> and edit-in-place for events/plans/products in the admin dashboard.
>
> IMPLEMENTATION STATUS (updated 2026-08-06, later same day): the venue
> scene is now walkable -- /venue/{slug} reuses the same WASD/click-to-move
> engine as /room (factored into frontend/static/js/scene-engine.js, shared
> by both room.js and venue.js) and adds hotspots for the bar, DJ booth,
> jukebox, and door. Walking up to one and clicking opens a conversation
> with an NPC (Bartender/DJ/Bouncer/Hacker), rendered by a generic dialogue
> modal off a new backend dialogue engine: backend/app/dialogue_data.py
> holds the actual conversation trees (edit this file to deepen/add
> dialogue -- see its module docstring for the node format) and
> backend/app/services/dialogue_service.py walks them, with a small
> action-name registry for nodes that need live data (the bar's menu off
> Products, the DJ's "what's on" off the active Event, the bouncer's status
> off access_service, and the Hacker's queue-skip mechanic). Two new
> endpoints: GET/POST /api/v/{slug}/npcs/{npc_id}/dialogue[/advance].
>
> The Hacker NPC (only appears once the jukebox is actually usable) lets a
> patron try to skip the jukebox queue by talking their way into it. Tier is
> driven by the patron's own membership at that venue (no admin-facing
> config needed): no active membership at a venue that has membership
> plans -- refuses outright; a membership below the venue's top-priced plan
> -- wants paying (reuses the venue's existing PriorityTier list/mock
> payment, no new payment code); the venue's top-priced plan -- does it for
> free (logs a $0 Transaction with kind="hacker_favor" for admin-side
> audit visibility). A venue with no membership plans at all defaults to
> "wants paying" for everyone, since there's no tier to prove there.
>
> NPCs currently reuse existing placeholder avatar sprites (no dedicated
> NPC art yet, per PLAN.md section 17) -- swapping one is a one-line change
> in dialogue_data.py. Bar/DJ/door props render as clickable hotspots now
> (previously decorative only); avatar/NPC-art authoring tooling and
> splitting dialogue_data.py into per-NPC files/modules are both deferred,
> the data shape already supports it without an engine change.
>
> IMPLEMENTATION STATUS (updated 2026-08-06, later still): section 8's QR
> *scanner* is built -- a new "QR Entry Scanner" panel in dashboard.html/
> dashboard.js (owner-session-gated, same as every other dashboard panel)
> posts to the existing POST /api/dashboard/qr-scan and renders its green/
> yellow/red verdict + reason + guest name. Manual token entry always works;
> a "Scan with Camera" button appears as a progressive enhancement when the
> browser exposes the native BarcodeDetector API (most Android browsers --
> hidden, not broken, on iOS Safari/others where it doesn't exist), decoding
> live camera frames with zero new dependencies.
>
> While boot-testing the scanner, found and fixed a real access-engine bug:
> evaluate_access() treated merely *holding* a QrPass row as its own
> entitlement (`_has_valid_pass`), but qr_service.get_or_create_pass mints
> one unconditionally for any identified patron -- so anyone could self-
> issue a standing bypass into a members-only/private venue with zero real
> entitlement behind it. Fix: removed that branch from the entry ladder
> entirely; a QrPass is now purely the scanner's lookup key (a digital ID
> badge), never an entitlement by itself -- scan_qr_pass already re-runs
> evaluate_access() at scan time against the badge holder's *current* real
> status (membership/event entitlement, or a pending AccessRequest for
> yellow), which is what actually decides the verdict. Confirmed via a
> fresh membership (green), no entitlement at all (red), and a pending
> access request (yellow) -- all three now correctly reachable end-to-end
> from a real QR badge. See access_service.py's module docstring for the
> full writeup.
>
> IMPLEMENTATION STATUS (updated 2026-08-06, later still): edit-in-place for
> events/membership plans/products is done -- the backend PATCH endpoints
> already existed (admin_update_event/plan/product in venue_router.py) and
> were unused from the dashboard; each "Create X" form in dashboard.html/
> dashboard.js now doubles as its own edit form (an `editing<X>Id` var per
> section flips the submit handler between POST and PATCH, a new "Edit"
> button per list row populates the form and a "Cancel" button resets it
> back to create mode). Also added the Products form's missing Description
> field while touching that form -- ProductCreate/Update already supported
> it, there was just no input for it. Boot-tested end-to-end with Playwright
> (create, edit, verify the list and the pre-filled edit form both reflect
> it) for all three.
>
> Still not built: posters/venue signage on the venue scene (explicitly
> deferred for later) and splitting dialogue_data.py into per-NPC files
> (premature -- current tree is small enough as one file).

Jsi senior full-stack vývojář, product architekt a UX/game designer v jednom. Pracuješ na existujícím projektu běžícím na Zeropsu pod doménou clubowna.com. Aktuálně tam je jednoduchý jukebox, ale chceme z něj vybudovat nový produkt:

CLUBOWNA = komunitní systém pro venues, členství, události, přístupová oprávnění a interaktivní moduly.

DŮLEŽITÉ:
- Zachovej funkční části současné aplikace, ale přerámuj je do širšího konceptu.
- Jukebox už není celý produkt, ale jen jeden modul.
- Chci MVP pro testovací režim v několika hospodách a barech.
- Celý produkt má mít styl top-down pixelart RPG hry ve very retro stylu.
- Implementuj to pragmaticky, bez zbytečného overengineeringu.
- Nejprve proveď audit kódu a napiš stručný plán, potom začni implementovat.
- Pokud narazíš na nejasnosti, zvol nejpraktičtější řešení a postupuj dál.
- Vše navrhuj tak, aby to šlo snadno dál rozšiřovat.

==================================================
1. PRODUKTOVÁ VIZE
==================================================

Clubowna není jen jukebox. Je to operační systém pro místa a jejich komunitu.

Základní use case:
- uživatel přijde na landing page,
- pohybuje se ve stylizovaném pixelart prostředí,
- přes interaktivní prvky vstoupí do systému,
- vybere si konkrétní venue,
- zobrazí se mu stav místa a aktuální dění,
- může místo navštívit jako návštěvník, člen, pozorovatel, nebo požádat pořadatele o vstup,
- může zakoupit jednorázové produkty/služby nebo členství,
- pokud má oprávnění, může vstoupit i na uzavřenou akci,
- přístup do místa se ověřuje QR kódem.

==================================================
2. STYL A HLAVNÍ UX KONCEPT
==================================================

Vizuální styl:
- top-down pixelart RPG
- retro atmosféra ve stylu SNES / GBA / staré PC adventure + lehký nightclub vibe
- jednoduché animace
- čitelné UI
- hravé, ale stále použitelné
- musí fungovat v browseru na desktopu i mobilu

Hlavní landing page:
- landing page = pokoj uživatele nebo šéfa klubu
- v pokoji je:
 - postel
 - plakát na stěně
 - počítač na stole
 - případně dveře / okno / dekorace
- uživatel se může pohybovat:
 - šipkami / WASD
 - nebo klikáním/tapováním
- při přiblížení nebo kliknutí na interaktivní objekt se spustí akce

Doporučené interakce:
- počítač = login / vstup do systému / výběr venue
- plakát = info / about / nápověda / co je Clubowna
- postel = guest mode / quick start / případně odpočinek jen jako stylový prvek
- dveře = opustit landing scene nebo vstup do mapy/venue hubu

Po přihlášení nebo v guest režimu se uživatel dostane do výběru kluboven / venues.

==================================================
3. VENUE SCÉNA
==================================================

Každá venue bude mít vlastní top-down pixelart prostor.

Povinné objekty v prostorách:
- bar
- hudební skříňka / jukebox
- stůl nebo booth s playery
- případně DJ(s), nebo žádný DJ podle typu akce
- vstupní dveře
- ostraha u dveří, pokud je omezený vstup
- různý počet návštěvníků / NPC podle typu a obsazenosti akce
- tematické propriety podle akce:
 - dort
 - balónky
 - svatební dekorace
 - cedule reserved
 - flower decor
 - birthday props
 - apod.

Dynamika venue:
- když je volný vstup, dveře jsou otevřené
- když je members-only režim, dveře mohou být zavřené a stojí tam ostraha
- když probíhá soukromá akce, venue zobrazuje omezený vstup
- podle typu přístupu se uživateli umožní:
 - vstoupit
 - sledovat jako pozorovatel
 - požádat pořadatele o vstup
 - koupit členství / jednorázový vstup / produkt
 - zobrazit QR pro kontrolu vstupu

==================================================
4. HLAVNÍ DOMÉNOVÝ MODEL
==================================================

Potřebuji čistý a rozšiřitelný doménový model.

Navrhni a implementuj alespoň tyto entity:

User
- id
- displayName
- avatar
- role(s)
- memberships
- purchases
- qrPass
- venueRelations

Venue
- id
- slug
- název
- popis
- adresa
- cover image / pixel scene config
- currentMode
- availableModules
- products
- membershipPlans
- accessRules
- events
- visibility

VenueMode
- public
- members_only
- private_event
- invite_only
- closed
- observer_allowed

Event
- id
- venueId
- title
- type (birthday, wedding, private party, club night, members session, etc.)
- start/end
- organizer
- accessMode
- observerMode
- requestAccessAllowed
- sceneProps
- guestCapacity
- publicVisibility

MembershipPlan
- id
- venueId
- name
- price
- interval (monthly/yearly/one-time if needed)
- perks / entitlements
- accessLevel
- qrAccessEnabled

Membership
- id
- userId
- venueId
- planId
- status
- validFrom
- validTo

Product / Service
- id
- venueId
- name
- description
- price
- type
- oneTime / recurring / includedInMembership
- enabled
- visibility
- grantsEntitlements

Purchase
- id
- userId
- venueId
- productId or membershipPlanId
- status
- createdAt

AccessRequest
- id
- userId
- venueId
- eventId
- organizerId
- status (pending/approved/rejected)
- createdAt

Entitlement
- id
- code
- description
- sourceType
- sourceId

QrPass
- id
- userId
- venueId
- token
- status
- expiresAt

ScreenMessage (pro budoucí modul)
- id
- venueId
- eventId
- userId
- content
- status

JukeboxSession (modulárně)
- id
- venueId
- eventId
- enabled
- accessMode
- currentState

==================================================
5. PŘÍSTUPOVÝ ENGINE
==================================================

Potřebuji jasnou logiku oprávnění.

Zásady:
- event overrideuje běžný režim venue
- soukromá akce nesmí být automaticky prolomena jen tím, že někdo má nějaké obecné členství
- pořadatel musí mít možnost výslovně povolit nebo zakázat:
 - pozorovatele
 - request access
 - členy konkrétních tierů
 - hosty členů

Implementuj Access Engine s logikou přibližně tohoto typu:

1. Je venue otevřená?
2. Probíhá aktivní event?
3. Má uživatel pozvánku?
4. Má explicitní event entitlement?
5. Má odpovídající membership entitlement?
6. Má jednorázový pass?
7. Lze požádat o vstup?
8. Lze vstoupit jen jako pozorovatel?
9. Jinak deny

Požaduji čistou interní strukturu typu:
- canViewVenue
- canViewEvent
- canObserveEvent
- canRequestAccess
- canEnterVenue
- canUseJukebox
- canShowQr
- canBuyProduct
- canJoinMembership

==================================================
6. VEŘEJNÝ PROFIL VENUE
==================================================

Každé venue musí mít zdarma přístupný veřejný profil.

Na veřejném profilu se zobrazí:
- název
- stručný popis
- aktuální stav
- co se tam právě děje
- jestli probíhá soukromá akce
- jestli je možné připojit se jako pozorovatel
- jestli je možné požádat pořadatele
- členství a jejich úrovně
- jednorázové produkty/služby
- dostupné moduly
- CTA akce:
 - Připojit se jako pozorovatel
 - Požádat o vstup
 - Stát se členem
 - Koupit jednodenní vstup
 - Zobrazit QR průkaz
 - Vstoupit do klubovny

==================================================
7. ADMIN PRO VENUE
==================================================

Venue musí mít možnost jednoduše nastavovat, co nabízí.

Chci jednoduchý admin/editor, kde půjdou pomocí checkboxů nebo přehledných přepínačů spravovat:

Dostupné moduly:
- Jukebox
- Pozorovatelé
- Request access
- QR vstup
- Screen messages
- Produkty
- Členství
- Dary / support
- Merch
- Lounge access
- Jednorázové vstupy

Přístupové režimy:
- volný vstup
- pouze členové
- soukromá akce
- akce na pozvánku
- schvalovaný vstup
- pouze vzdálené sledování

Produkty/služby:
- jednorázové
- dlouhodobé
- součást členství

Chci, aby venue admin mohl:
- založit venue
- založit event
- nastavit scénu a její stav
- přidávat produkty
- přidávat membership plány
- zapínat/vypínat moduly
- nastavovat pravidla přístupu
- povolovat/zakazovat membership tierům vstup na konkrétní eventy
- schvalovat žádosti o vstup

==================================================
8. QR VSTUP A SCANNER
==================================================

Pokud je venue members-only nebo má uzavřené akce, vstup se bude kontrolovat pomocí QR.

Požaduji:
- uživatelskou obrazovku s QR průkazem
- scanner režim pro personál / venue staff
- základní validaci vstupu

Výstupy scanneru:
- zelená = přístup povolen
- žlutá = vyžaduje schválení / pending
- červená = přístup zamítnut / neplatné oprávnění

Nepoužívej v QR citlivé otevřené údaje. Použij token-based přístup.

==================================================
9. JUKebox JAKO MODUL
==================================================

Jukebox zůstává, ale pouze jako modul v rámci venue.

Důležité:
- architekturu dělej provider-agnostic
- nepřivazuj logiku placených benefitů přímo k YouTube
- odděl:
 - music request module
 - membership logic
 - event access
 - products / gifts
- v UI prezentuj jukebox jako součást klubovny, ne jako celou aplikaci

Pro MVP stačí základní integrace současného řešení, ale ulož to do modulární struktury.

==================================================
10. HERNÍ POHYB A INTERAKCE
==================================================

Pohyb:
- arrow keys / WASD
- click-to-move nebo tap-to-move fallback
- interaktivní hotspoty

Pokud by plnohodnotný game engine byl příliš těžkopádný, zvol nejjednodušší robustní řešení:
- lehká 2D vrstva
- sprite-based scene
- případně DOM/CSS + absolutní pozicování + jednoduchý pohyb
- nebo canvas, pokud je to ve stávajícím stacku čistší

Chci funkční a rychlý MVP, ne technologickou exhibici.

==================================================
11. MVP ROZSAH
==================================================

Do první verze implementuj:

A. Hlavní landing scénu – pokoj
- pohyb
- interaktivní počítač
- login entry / guest entry
- vstup do seznamu nebo mapy kluboven

B. Seznam nebo hub venue
- minimálně 3–5 seed venues pro demo/test
- různý stav venue:
 - veřejná
 - members only
 - soukromá narozeninová oslava
 - svatba
 - klubová noc

C. Venue detail / venue scéna
- pixelart klubovna
- stav dveří
- ostraha
- NPC hustota
- propriety dle akce
- základní interakce

D. Access system
- membership plans
- request access
- observer mode
- QR pass
- venue status logic

E. Venue admin MVP
- zapínání modulů
- nastavení produktů
- nastavení membership planů
- vytvoření eventu
- schvalování žádostí

F. Jukebox modul
- napoj stávající jednoduchou funkcionalitu jako modul

==================================================
12. TESTOVACÍ DEMO DATA
==================================================

Vytvoř seed/demo data pro alespoň tato místa:

1. Pixel Pub
- veřejná hospoda
- otevřená
- basic jukebox
- observer mode off

2. Neon Den
- members only bar
- QR kontrola
- více membership tierů

3. Birthday Basement
- soukromá narozeninová oslava
- dort, balónky
- observer mode on
- request access on

4. Wedding Hall
- svatba
- uzavřený vstup
- pozorovatelé mohou sledovat
- dary a přání jako budoucí modul placeholder

5. Night Cartridge
- klubová noc s DJ booth
- veřejný event
- větší crowd

==================================================
13. UI / NAVIGACE / ARCHITEKTURA
==================================================

Požaduji:
- přehledné routy
- jasné oddělení public pages, authenticated pages a venue admin části
- rozumný component system
- čistou strukturu kódu

Navrhni a implementuj vhodnou strukturu například ve stylu:
- app shell
- game scene layer
- venue domain
- membership domain
- access engine
- admin tools
- reusable UI

Dbej na:
- čitelnost
- snadnou rozšiřitelnost
- žádné zmatky mezi product logic a game presentation

==================================================
14. NEPŘEHÁNĚT
==================================================

Teď nechci:
- složité účetnictví
- ostré platební workflow
- komplikované reklamní systémy
- univerzální kreditní peněženku
- plné marketplace settlementy
- přehnaně složitou ekonomiku

Pokud potřebuješ platby nebo dary v MVP, udělej zatím placeholder nebo mock/test mode.

==================================================
15. VÝSTUPY, KTERÉ OD TEBE CHCI
==================================================

Postupuj takto:

Krok 1:
- proveď audit stávajícího projektu
- stručně shrň současný stav
- navrhni implementační plán v 5–8 bodech
- napiš, co zachováš, co refaktoruješ a co vytvoříš nově

Krok 2:
- začni implementovat MVP
- pracuj po menších logických blocích
- po každém větším kroku stručně napiš, co jsi udělal

Krok 3:
- na konci napiš:
 - co je hotové
 - co je zatím placeholder
 - co doporučuješ jako další fázi

==================================================
16. AKCEPTAČNÍ KRITÉRIA
==================================================

Implementace bude považována za úspěšnou, pokud půjde:

- otevřít clubowna.com a vidět pixelart landing room
- pohybovat se po room scéně
- přes počítač vstoupit do výběru venue
- zobrazit několik demo venues
- u každé venue vidět stav a typ akce
- u soukromé akce se připojit jako pozorovatel nebo požádat o vstup
- vstoupit do members-only venue s platným membership nebo QR
- zobrazit QR průkaz
- ve scanner režimu zvalidovat vstup
- v admin části zapnout/vypnout moduly venue
- u venue zobrazit membership plány a produkty
- vstoupit do venue scény s jukeboxem jako modulem

==================================================
17. DESIGN POZNÁMKY
==================================================

Chci, aby to působilo zábavně, nostalgicky a originálně, ale ne chaoticky.
Musí to být:
- retro
- hravé
- pixelart
- komunitní
- klubové
- lehce ironické / cool
- stále dostatečně přehledné pro reálné použití v hospodách a barech

Pokud budeš dělat placeholder grafiku:
- použij jednoduché pixelart boxy / tiles / barevné bloky / sprite placeholders
- neblokuj implementaci čekáním na finální art

Teď začni krokem 1: proveď audit projektu, navrhni plán a potom přejdi k implementaci.
