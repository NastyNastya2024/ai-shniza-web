/* Official {AI}-шница showcase works — open prompts + storyboard refs */
(function () {
  var V = window.VITRINA = window.VITRINA || { works: [], creators: [] };
  V.works = V.works || [];
  V.creators = V.creators || [];
  if (!V.creators.some(function (c) { return c.id === "aish"; })) {
    V.creators.push({
      id: "aish",
      name: "{AI}-шница",
      nick: "aishnitsa",
      handle: "aishnitsa",
      works: 1,
      grad: "#FF8A2B,#F2668B",
      about: "Официальные работы {AI}-шницы · открытые промпты",
      contacts: [{ net: "site", login: "aishnitsa.ru", show: true }]
    });
  }
  var extra = [
  {
    "id": "aish-invisible-dancer",
    "file": "invisible-dancer",
    "title": "Invisible Dancer",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1200,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/invisible-dancer.jpg",
    "video": "works/invisible-dancer.mp4",
    "published": true,
    "prompt": "Create a 10-second, 9:16 ultra-photorealistic luxury fashion CGI video following all 20 storyboard frames in exact order. One invisible dancer wearing a floating oversized cable-knit sweater, matching beanie and designer sunglasses. Three looks: ivory → vivid orange → deep Bordeaux. Preserve identical clothing geometry, knitted patterns, proportions and glasses frame. Clean sky-blue studio, soft sunlight, realistic wool texture. No visible body, hands, legs or shoes. Continuous energetic dancing, dynamic camera orbits, extreme macro, aggressive speed ramps, no cuts or slideshow transitions. 0–2s: Ivory outfit floats, then comes alive. Invisible dancer performs sharp shoulder pops, chest rolls, sideways steps and exaggerated marching. Sleeves swing naturally, sweater stretches around invisible arms, beanie and glasses follow head movements. Camera pushes in, counter-tracks and performs a fast 90° orbit before dropping to an extreme low angle. 2–2.4s: During a sharp shoulder turn, ivory knitted loops begin physically unraveling from sleeve to shoulder and chest. Extreme macro reveals individual wool stitches releasing into long connected threads. 2.4–2.8s: The sweater and beanie spectacularly unravel into hundreds of continuous ivory yarn strands, forming an elegant three-dimensional spiral around the still-dancing invisible body. Camera rapidly orbits 180°. 2.8–3.2s: Bright orange threads enter the vortex, interweaving into real knitted loops, progressively rebuilding the identical sweater and beanie. Extreme macro transitions into a rapid pull-back. Sunglass lenses turn amber. 3.2–5.5s: Dancer completes the uninterrupted turn in the fully orange outfit, then performs powerful shoulder hits, body waves, confident marching toward camera and a playful glasses adjustment. Dynamic close tracking, low frontal reverse tracking and eyewear macro. At 5s the dancer launches into a fast full-body spin with a dramatic 270° counter-orbit. 5.5–6s: Orange sweater begins unraveling from the lower hem upward, individual knitted loops opening into long orange yarn strands that spiral outward during the continuous spin. 6–6.5s: Deep Bordeaux threads sweep inward through the orange yarn vortex, physically weaving themselves into the identical sweater and beanie. Orange strands retreat as Bordeaux knitted loops progressively form. Fast 180° camera orbit. 6.5–7s: Final Bordeaux stitches tighten, completing the new outfit as the dancer finishes spinning. Sunglass lenses become dark cherry. Sharp frontal reveal and hard camera brake. 7–9s: Confident Bordeaux dance: chest pops, shoulder rolls, side steps, head snaps, dramatic forward lean, sleeve raised toward glasses, fast turns and two rhythmic steps. Dynamic 120–180° camera orbits and speed ramps. 9–10s: Final asymmetrical Bordeaux fashion pose, tilted beanie, cherry sunglasses facing camera, one sleeve raised. Smooth cinematic push-in and hold. CRITICAL TRANSITION: Every color change must be a beautiful physical YARN DISINTEGRATION → REWEAVE animation. Individual knitted loops visibly loosen, unravel into continuous wool filaments, swirl into layered helical ribbons, then physically interlock into new-color stitches. No instant recoloring, dissolves, particles, teleportation or duplicate outfits. The dancer never stops moving during transformations. Beanie unravels and reknits synchronously; only sunglasses lens tint changes. Preserve one invisible dancer, continuous motion, constant background and realistic cloth physics. No visible anatomy, smoke, flashes, text or logos. Energetic 130 BPM funky fashion-house music, synchronized transformation accents and tactile wool sounds. Premium cinematic realism and seamless sensory speed-ramp editing.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/invisible-dancer-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "fashion",
      "cgi",
      "invisible-dancer",
      "yarn",
      "open-prompt"
    ]
  },
  {
    "id": "aish-pressure-surgery",
    "file": "pressure-surgery",
    "title": "Pressure Surgery",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 980,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/pressure-surgery.jpg",
    "video": "works/pressure-surgery.mp4",
    "published": true,
    "prompt": "Create a 10-second vertical 9:16 ultra-photorealistic automotive ASMR video in a sterile white detailing studio. Preserve the same McLaren throughout: exact proportions, black carbon roof/aero, black wheels and active rear wing. First-person detailer POV, matte-black gloves. Start with the car completely covered in thick brown mud over scratched dull-grey paint. Pressure-wash in aggressive speed ramps: blast mud from body, wheel arches and side intake, physically revealing grey paint, black wheels and carbon; cover the car with dense white foam, wipe with a wash mitt, then rinse clean. Reveal heavy scratches and swirl marks with an inspection light. Rapidly sand/prep the damaged grey paint, microfiber wipe and mask exposed carbon. Extreme macro: spray gun physically transforms the surface with a moving GREY → bright saturated ORANGE METALLIC paint boundary; rapidly paint hood, doors and rear panels while carbon remains black. Apply clear coat, then polish to a deep mirror finish. Peel masking tape, revealing a perfect orange/carbon edge; show water beading on the finished paint. Final low front 3/4 hero shot: POV hand presses the key, engine starts, body subtly shudders, LED headlights illuminate; active rear wing rises slowly and mechanically → CLICK; engine revs and the orange McLaren launches straight toward the camera → HARD CUT TO BLACK. Realistic mud, water, foam, sanding and paint physics; speed ramps only on physical actions; no morphing, magical cleaning or digital color changes.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/pressure-surgery-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "automotive",
      "asmr",
      "mclaren",
      "detailing",
      "open-prompt"
    ]
  },
  {
    "id": "aish-liquid-silver-orbit",
    "file": "liquid-silver-orbit",
    "title": "Liquid Silver Orbit",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1100,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/liquid-silver-orbit.jpg",
    "video": "works/liquid-silver-orbit.mp4",
    "published": true,
    "prompt": "Create a 10-second 16:9 ultra-photorealistic luxury jewelry video, strict first-person macro POV. One elegant female hand with nude manicure rests on a clean matte-black table against a pure black background, premium studio lighting. 0–1s: one liquid-silver drop falls beside the ring finger. 1–2s: it splits into reflective silver spheres that glide toward the finger, climb onto the skin and become liquid streams. 2–3s: silver flows around the finger from both sides. 3–4s: the streams meet and merge into one liquid band. 4–5s: the band smooths and solidifies into a polished silver ring. 5–6s: remaining silver rises from the ring and forms four symmetrical prongs. 6–7s: a clear spherical crystal droplet forms between the prongs. 7–8s: the sphere progressively develops precise facets and becomes a brilliant-cut diamond. 8–9s: four prongs close naturally around the diamond. 9–10s: finished ring hero shot; the hand slowly rotates while the camera performs a tight macro orbit, ending with one controlled diamond sparkle. Keep every transformation continuous and physically connected with realistic liquid-metal flow, surface tension and reflections. No instant morphing, magic particles, extra hands, objects, jewelry, text or logos.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/liquid-silver-orbit-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "jewelry",
      "luxury",
      "macro",
      "liquid-metal",
      "open-prompt"
    ]
  },
  {
    "id": "aish-apartment-speed-ramp",
    "file": "apartment-speed-ramp",
    "title": "Apartment Speed-Ramp",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 870,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/apartment-speed-ramp.jpg",
    "video": "works/apartment-speed-ramp.mp4",
    "published": true,
    "prompt": "Create a 10-second 9:16 photorealistic first-person SPEED-RAMP video. 0–1s: exterior, black-gloved male hand points at an apartment window. 1–1.5s: explosive zoom through the window. 1.5–3s: hard brake, smooth glide through living room with beige sofa. 3–3.4s: fast zoom through doorway. 3.4–5s: brake and glide through warm modern bedroom, close details of bed and materials. 5–5.4s: fast zoom through doorway to kitchen. 5.4–7.7s: brake, smooth kitchen glide around dark stone island, close material details, then stop. 7.7–9.5s: extreme reverse rewind through kitchen → bedroom → living room → window → exterior. 9.5–10s: brake at exact starting position, same hand pointing at same window. One continuous camera path, strong motion blur only during acceleration, realistic physics, consistent architecture and furniture, no morphing or cuts.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/apartment-speed-ramp-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "architecture",
      "speed-ramp",
      "pov",
      "interior",
      "open-prompt"
    ]
  },
  {
    "id": "aish-lime-hypercar-build",
    "file": "lime-hypercar-build",
    "title": "Lime Hypercar Build",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:15",
    "creator": "aish",
    "likes": 1320,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/lime-hypercar-build.jpg",
    "video": "works/lime-hypercar-build.mp4",
    "published": true,
    "prompt": "Create a 10-second, vertical 9:16 ultra-photorealistic hypercar assembly commercial following all 20 storyboard stages chronologically. Preserve one identical aggressive racing hypercar with sharp LED headlights, sculpted body, black carbon aero, five-spoke wheels and rear wing. Initially matte graphite gray, finally glossy acid lime green. Pristine white automotive workshop, reflective light-gray floor, bright studio lighting. Strict first-person mechanic POV during assembly and painting, showing only two masculine hands in black technical gloves. Cinematic extreme macros, explosive crash zooms, whip-pans, rapid push-ins, elastic pullbacks, hard cuts and aggressive speed ramps. 0–0.4s: Wide POV of partially assembled gray hypercar with components arranged nearby; hands enter, explosive push-in. 0.4–0.8s: Hands align a metallic chassis bracket; extreme macro zoom. 0.8–1.2s: Electric impact driver tightens fastener; sharp click, camera recoil. 1.2–1.6s: Hands lower graphite front panel onto chassis; camera dives with it. 1.6–2s: Fingers press headlight panel seam; rapid lateral whip. 2–2.4s: Hands install sculpted side intake panel; fast side tracking. 2.4–2.8s: Carbon aerodynamic insert locks into place; extreme texture macro. 2.8–3.2s: Hands mount black racing wheel onto hub; aggressive low POV push-in. 3.2–3.6s: Tool tightens wheel fastener; crash zoom and snap pullback. 3.6–4s: Hands secure carbon rear wing; rapid rear tracking. 4–4.4s: Explosive pullback reveals fully assembled gray hypercar; sudden camera brake. 4.4–4.8s: Right hand raises professional spray gun; nozzle macro and focus pull. 4.8–5.2s: Spray gun applies fluorescent lime paint across gray panel; close surface tracking. 5.2–5.6s: Rapid lateral flyby reveals progressive green coating across bodywork; carbon remains black. 5.6–6s: Dramatic pullback reveals completely glossy acid-lime hypercar. 6–6.5s: Fast controlled orbit around finished car; dramatic low front three-quarter hero shot. 6.5–7s: Engine ignites with powerful roar, LED headlights illuminate; explosive headlight crash zoom. 7–7.7s: Extreme rear wheel and diffuser macro; engine revs, suspension loads, rapid camera slide. 7.7–8.7s: Hypercar launches diagonally toward camera with physically rotating wheels, realistic acceleration, aggressive tracking and speed ramp. 8.7–10s: Car rushes directly toward lens; camera violently dodges sideways as it blasts past, then whip-pans 180 degrees into low rear three-quarter tracking as the car accelerates away. Energetic industrial electronic soundtrack, 135 BPM, synchronized tool clicks, spray hiss, engine ignition and escalating exhaust roar. Preserve exact vehicle geometry, physical assembly, progressive paint application, realistic motion and continuous environment. No visible people, extra cars, floating parts, magical transformations, smoke, sparks, captions or graphics.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/lime-hypercar-build-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "automotive",
      "hypercar",
      "assembly",
      "lime",
      "open-prompt"
    ]
  },
  {
    "id": "aish-invisible-man-looks",
    "file": "invisible-man-looks",
    "title": "Invisible Man Looks",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1450,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/invisible-man-looks.jpg",
    "video": "works/invisible-man-looks.mp4",
    "published": true,
    "prompt": "Create a 10-second, vertical 9:16 ultra-photorealistic CGI fashion commercial following 18 chronological storyboard shots. ONE COMPLETELY INVISIBLE MAN throughout: no visible skin, face, head, hands, legs, body or mannequin. Only realistic hollow clothing maintaining human shape, natural fabric movement and floating sunglasses. Three exact outfits: LOOK 1 — brown ribbed polo with white collar, beige trousers, white sneakers with black stripes, brown sunglasses; LOOK 2 — emerald-green jacket, cream sweater, beige trousers, green-white sneakers, sunglasses and crossbody bag; LOOK 3 — burgundy bomber jacket, white T-shirt, black trousers, white sneakers, black sunglasses and silver necklace. Infinite seamless warm-beige studio, soft sunlight, realistic shadows. Dynamic low-angle tracking, explosive zooms, smooth orbits, macro details, speed ramps and hard stops. 0–0.5s: Brown outfit stands confidently, full-body push-in. 0.5–1s: Two stylish steps forward, adjusts collar, low-angle tracking. 1–1.5s: Head tilt, sunglasses adjustment, 60° orbit into fabric macro. 1.5–2s: Brown outfit begins disintegrating into thousands of tiny realistic textile particles, rapid pullback. 2–2.5s: Brown particles violently fly LEFT while green particles simultaneously enter from RIGHT, wide cinematic crossover. 2.5–3s: Green particles reconstruct sneakers, trousers, sweater, jacket and accessories on the invisible body, sharp camera push-in. 3–3.5s: Green outfit complete, shoulder snap and jacket adjustment. 3.5–4s: Relaxed cross-step, side-step and shoulder roll, low-angle tracking. 4–4.5s: Adjusts crossbody strap and sunglasses, upward camera glide. 4.5–5s: Stylish 90° turn, hand inside pocket, smooth counter-orbit. 5–5.5s: Green outfit rapidly disintegrates into thousands of textile fragments, explosive pullback. 5.5–6s: Green particles shoot LEFT while burgundy, black and white particles rush in from RIGHT. 6–6.5s: Particles reconstruct white sneakers, black trousers, white T-shirt, burgundy jacket and accessories, dramatic camera brake. 6.5–7s: Sharp jacket adjustment, confident head tilt, low-angle close-up. 7–7.6s: Powerful runway walk toward camera, cross-steps, shoulder hits, aggressive reverse tracking. 7.6–8.3s: Fast 180° spin and return, jacket flares naturally, dynamic counter-orbit. 8.3–9.1s: Two energetic steps, adjusts floating sunglasses, sharp freeze, rapid low-to-high camera rise. 9.1–10s: Final full-body burgundy hero pose, one invisible hand in pocket, other touching sunglasses, elegant camera pullback and static hold. STRICT PARTICLE PHYSICS: outgoing outfits always dissolve and fly LEFT, incoming particles always arrive from RIGHT and physically assemble into detailed garments. Preserve identical invisible body, exact outfit designs, seamless beige background and realistic motion. No visible body parts, extra objects, smoke, flashes or text. Energetic 130 BPM fashion-house music, synchronized footsteps and particle whooshes.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/invisible-man-looks-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "fashion",
      "cgi",
      "invisible-man",
      "particles",
      "open-prompt"
    ]
  },
  {
    "id": "aish-cherry-red-manicure",
    "file": "cherry-red-manicure",
    "title": "Cherry Red Manicure",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1050,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/cherry-red-manicure.jpg",
    "video": "works/cherry-red-manicure.mp4",
    "published": true,
    "prompt": "Create a continuous 10-second ultra-photorealistic luxury manicure commercial, vertical 9:16, following all 12 storyboard frames chronologically. Strict first-person POV of a nail technician wearing black nitrile gloves, working on the same client's hand over a clean black manicure table. Premium cinematic lighting, elegant macro photography, shallow depth of field, smooth stabilized camera movements, vivid glossy cherry-red polish, realistic textures and reflections. 0–0.8s: Gloved hands approach the client's natural nails, smooth POV push-in. 0.8–1.6s: Extreme macro of gently filing a nail. 1.6–2.4s: Precise cuticle trimming with metal nippers. 2.4–3.2s: Apply transparent base coat in one smooth stroke. 3.2–4s: Lift a brush from a red polish bottle, showing thick flowing lacquer. 4–4.8s: Slowly apply the first glossy red stroke from cuticle to tip. 4.8–5.6s: Continue evenly coating the nail with precise brush movements. 5.6–6.4s: Refine polish edges using a thin detailing brush. 6.4–7.2s: Guide the client's red nails into a black curing lamp glowing red. 7.2–8s: Reveal finished glossy red nails supported by black-gloved fingers. 8–8.5s: Smooth macro slide across the flawless manicure. 8.5–10s: Elegant final hero shot of the client's hand displaying all five glossy cherry-red nails above a reflective black surface, softly blurred red flowers in the background, slow cinematic camera slide. Maintain identical hands, nail shapes, colors, realistic physical interactions and continuous POV throughout. Fast-to-slow pacing, refined instrumental music and subtle synchronized manicure sounds. No faces, text, logos, captions, voiceover or advertising inserts.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/cherry-red-manicure-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "beauty",
      "manicure",
      "macro",
      "luxury",
      "open-prompt"
    ]
  },
  {
    "id": "aish-beach-house-origami",
    "file": "beach-house-origami",
    "title": "Beach House Origami",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1180,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/beach-house-origami.jpg",
    "video": "works/beach-house-origami.mp4",
    "published": true,
    "prompt": "Create a 10-second vertical 9:16 ultra-photorealistic luxury CGI video in one continuous shot on a sunny tropical beach with white sand, turquoise ocean and blue sky. First-person POV, two black-gloved male hands. A beige sofa stands at the shoreline. Hand swipes left, sofa flies away. A beige bed flies in from the right, another swipe removes it. A sculptural beige lounge chair with two bright-orange cushions flies in and is selected by pointing. Hands disappear. Camera rapidly orbits the chair as a luxury open-air beach lounge dynamically assembles around it. Travertine floor panels unfold outward, beige walls rise, a massive curved terracotta-orange wall forms, geometric side walls and dark teak details lock into place. Roof panels fold down, teak ceiling louvers assemble, panoramic ocean openings unfold. Coffee table, pouf, console and floor lamp assemble through folding movements, beige rug unrolls beneath the chair. Extreme macro of upholstery and orange cushions, then fast 180° camera orbit revealing the completed architecture. Camera pulls back over the water into a spectacular wide hero shot of the luxury coastal lounge. Extreme sensor speed ramps, dynamic FPV camera, realistic physics, precise FLAT → FOLD → ROTATE → LOCK construction, seamless transitions, consistent furniture and architecture, natural sunlight, no cuts or magical appearances.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/beach-house-origami-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "architecture",
      "cgi",
      "beach",
      "origami",
      "open-prompt"
    ]
  },
  {
    "id": "aish-diamond-kiss",
    "file": "diamond-kiss",
    "title": "Diamond Kiss",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1260,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/diamond-kiss.jpg",
    "video": "works/diamond-kiss.mp4",
    "published": true,
    "prompt": "Create a 10-second vertical 9:16 ultra-photorealistic luxury jewelry commercial following all 15 storyboard frames in exact order. Pure black background, bright cinematic beauty lighting, crystal-clear macro details, deep focus, no blur. Show only the same woman's lower face with full glossy ruby-red lips, natural white teeth, and one rose-gold ring with a large round diamond. 0–0.6s: Symmetrical frontal close-up, lips holding the ring between teeth, slow push-in. 0.6–1.2s: Lips open wider, revealing the diamond and gold band. 1.2–1.8s: Low-angle macro looking upward at the diamond between red lips. 1.8–2.4s: Smooth 45° diagonal camera orbit revealing the gold setting. 2.4–3s: Extreme sharp diamond macro with natural red reflections. 3–3.6s: 50° side orbit showing the lips' profile and ring. 3.6–4.2s: Frontal view, lips form a subtle smile, revealing white teeth. 4.2–4.8s: Elevated 35° angle looking down at the diamond. 4.8–5.4s: Two elegant fingers with glossy red nails enter and gently grip the gold band. 5.4–6s: Fingers smoothly pull the ring forward from the mouth, lips gently close. 6–6.6s: Diagonal close-up of the ring held in front of red lips. 6.6–7.2s: Fingers rotate the ring 45°, revealing diamond facets, prongs and gold band. 7.2–7.8s: Symmetrical frontal composition, diamond centered before slightly parted lips. 7.8–8.6s: Smooth 90° cinematic camera orbit around the ring and lips. 8.6–10s: Final diamond hero shot, gemstone centered between red-manicured fingertips, glossy red lips behind, slow push-in and sharp static hold. Maintain identical facial features, ring geometry, realistic physical interactions, brilliant diamond reflections and perfect visual continuity. Premium electronic ambient music with subtle crystalline accents. No eyes, full face, extra objects, text, blur or dialogue.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/diamond-kiss-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "jewelry",
      "luxury",
      "macro",
      "beauty",
      "open-prompt"
    ]
  },
  {
    "id": "aish-canyon-sofa-select",
    "file": "canyon-sofa-select",
    "title": "Canyon Sofa Select",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 990,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/canyon-sofa-select.jpg",
    "video": "works/canyon-sofa-select.mp4",
    "published": true,
    "prompt": "Create a 10-second vertical 9:16 ultra-photorealistic luxury furniture CGI video following all 18 storyboard frames in chronological order. One continuous first-person POV inside a spectacular narrow sandstone canyon with towering curved walls and a reflective floor. Camera completely locked, fixed perspective, no cuts or zooms. Only two masculine hands wearing stylish black leather gloves appear. Three luxury sofas: sculptural red textured sofa, white rounded bouclé sofa and emerald-green velvet sofa. 0–0.5s: Red sofa stands centered in the warm orange canyon, golden sunlight, both gloved hands visible. 0.5–1.7s: Right hand sharply swipes right to left, red sofa slides off left while white sofa simultaneously enters from right. A spectacular freezing wave follows the gesture, rapidly spreading crystalline frost across sandstone walls, covering rock ledges and ground with realistic snow. 1.7–2.6s: White sofa stops perfectly centered, entire canyon becomes a beautiful icy winter landscape with cold blue-white lighting and delicate snow crystals. 2.6–3.0s: Right hand reaches toward the white sofa, revealing its soft bouclé texture without touching it. 3.0–4.2s: Second sharp right-to-left hand swipe, white sofa slides left while emerald-green sofa enters from right. A powerful organic transformation wave melts the snow, exposes wet sandstone and spreads vibrant green moss across the canyon walls, following every natural rock curve. 4.2–5.5s: Green sofa stops centered, ferns rapidly unfold from rock cracks, hanging plants grow downward, snow disappears and lush moss covers the ground. 5.5–6.7s: Cold lighting transforms into beautiful warm golden sunlight streaming through the canyon opening, illuminating the emerald velvet sofa. Hands slowly lower. 6.7–7.4s: Final leaves unfold, plants gently sway and the lush environment settles naturally. 7.4–8.4s: Right hand points at the green sofa and opens its palm to confirm selection. 8.4–10s: Both hands disappear below frame, revealing a perfectly still cinematic hero shot of the emerald sofa surrounded by moss-covered sandstone, lush ferns and golden sunbeams. Maintain identical canyon geometry, camera position and sofa scale throughout. Each sofa moves horizontally as a separate solid object, never morphs. Exactly two swipes, three sofas and one location. Smooth synchronized transformations, realistic physics, premium lighting, detailed textures, natural shadows, cinematic ambient music and synchronized elemental sound effects. No camera movement, teleportation, extra objects, people, text or overlays.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/canyon-sofa-select-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "furniture",
      "cgi",
      "canyon",
      "luxury",
      "open-prompt"
    ]
  },
  {
    "id": "aish-orange-skincare",
    "file": "orange-skincare",
    "title": "Orange Skincare",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1140,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/orange-skincare.jpg",
    "video": "works/orange-skincare.mp4",
    "published": true,
    "prompt": "Create a 10-second, 9:16 ultra-photorealistic luxury skincare commercial following all 15 storyboard shots in exact order. One identical beautiful red-haired woman with green eyes, freckles, natural skin and voluminous copper hair, wearing a vibrant orange designer top. One identical glossy orange cosmetic jar containing silky ivory cream. Pure white studio, warm beauty lighting, realistic oranges, premium macro cinematography, dynamic camera movements, smooth orbits, speed ramps and sharp focus transitions. 0–0.6s: Extreme orange-slice macro, explosive camera pullback reveals the model peeking behind it. 0.6–1.2s: Orange cream jar resting on stacked oranges, smooth 60° camera orbit. 1.2–1.8s: Model covers one eye with an orange slice, then lowers it, revealing both green eyes. 1.8–2.4s: Macro of hands twisting open the orange jar, revealing creamy ivory texture. 2.4–3s: Extreme macro of fingertip lifting silky cream into a soft peak. 3–3.6s: Beauty close-up, model gently applies a cream dot to her cheek. 3.6–4.2s: Extreme skin macro, fingertip massages cream in small circles, revealing natural hydrated glow. 4.2–4.8s: Model smiles between two large foreground oranges, subtle camera push-in. 4.8–5.4s: High-speed macro of fresh orange juice droplets splashing beside the closed jar. 5.4–6s: Model holds jar beneath her lips, rotating it slightly, quick product-to-lips rack focus. 6–6.7s: Frontal portrait holding two oranges beside her head, playful eyebrow raise, 30° camera arc. 6.7–7.4s: Jar presented on extended open palm, foreground product focus, smooth 60° orbit revealing her profile. 7.4–8.2s: Dynamic editorial posing with jar and orange half: head tilt, shoulder turn, direct gaze, natural hair movement, controlled speed ramp. 8.2–9s: Extreme beauty close-up, fingertips glide across glowing freckled cheek, gentle push-in. 9–10s: Final hero portrait, model smiling with orange jar beside her face, whole oranges and slices below, smooth push-in, HARD BRAKE, final hold. Preserve exact identity, product geometry, shot timing and sequence. Rhythmic premium cuts, realistic skin pores, natural physics, cinematic motion blur, 115 BPM luxury summer electronica and subtle ASMR. No extra people, text, logos, artificial effects or background changes.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/orange-skincare-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "beauty",
      "skincare",
      "macro",
      "orange",
      "open-prompt"
    ]
  },
  {
    "id": "aish-red-mannequin-transform",
    "file": "red-mannequin-transform",
    "title": "Red Mannequin Transform",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1280,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/red-mannequin-transform.jpg",
    "video": "works/red-mannequin-transform.mp4",
    "published": true,
    "prompt": "Create a 10-second vertical 9:16 ultra-photorealistic cinematic fitness CGI video following all 20 storyboard frames chronologically. One identical glossy-black faceless female mannequin transforms progressively from obese, with a large belly and thick thighs, into a toned athletic figure. She initially wears a white sports bra, white leggings and white sneakers inside a luxurious dark graphite gym with warm vertical LED lighting. 0–1.4s: Dynamic squats, extreme anatomical macros revealing glowing red quadriceps and glutes, powerful speed ramps and 90° camera orbit. 1.4–2.45s: First visible body reduction, energetic alternating lunges with red muscle activation. 2.45–3.5s: Explosive running, fast tracking shots, synchronized red muscle highlights and second progressive slimming stage. 3.5–4.2s: Forearm plank with glowing red abdominal and core anatomy. 4.2–5.3s: Resistance-band exercises, red shoulder and back muscle activation, third transformation into an athletic physique. 5.3–6.4s: Rapid squat–lunge–plank–running montage, aggressive speed ramps, 180° orbit revealing the final toned body. 6.4–7s: Spectacular seamless wardrobe transformation into a luxurious flowing ruby-red evening dress and matching high heels. 7–8.3s: Elegant runway walk, graceful rotations, dramatic low-angle tracking and fashion poses. 8.3–10s: Stunning final full-body fashion hero shot, one hand on waist, red architectural lighting, slow cinematic push-in and confident static pose. Maintain exact character identity, realistic anatomy, gradual visible weight loss, smooth transitions, intense red muscle visualization, dynamic camera choreography, 140 BPM electronic soundtrack and physically accurate movements. No additional characters, text, logos or abrupt transformations.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/red-mannequin-transform-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "fitness",
      "cgi",
      "fashion",
      "transformation",
      "open-prompt"
    ]
  },
  {
    "id": "aish-mclaren-sky-launch",
    "file": "mclaren-sky-launch",
    "title": "McLaren Sky Launch",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1520,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/mclaren-sky-launch.jpg",
    "video": "works/mclaren-sky-launch.mp4",
    "published": true,
    "prompt": "Create a 10-second vertical 9:16 ultra-photorealistic cinematic CGI video featuring one identical orange-red McLaren 765LT, strictly preserving its visual passport, original body geometry, black roof and carbon details. Follow all 24 storyboard actions chronologically. Inside a pristine white futuristic garage, a wheel-less McLaren stands on a hydraulic platform. First-person POV: two masculine hands in black gloves sweep outward, triggering four black wheels to fly inward along robotic rails, precisely align with the hubs and mechanically lock into place. The platform lowers the car. Another hand gesture activates an engineering transformation: rear carbon panels open on hinges, internal mechanisms unfold, four ducted lift fans deploy on telescopic rails, compressed-air reservoirs and pneumatic pipelines connect, thrust-vectoring nozzles rotate, carbon stabilizers extend and twin rear propulsion turbines lock into position. Every component moves through visible mechanical joints, actuators and precision engineering, without magical morphing. A third hand gesture triggers architectural origami: white garage walls fold outward, ceiling panels retract and the floor transforms into an open launch platform beneath a brilliant blue sky. Pneumatic valves activate, powered lift fans accelerate, powerful downward airflow creates realistic turbulence, and the McLaren smoothly rises into a stable hover. After a dramatic pause, explosive vertical thrust launches the car into the sky. The camera accelerates upward into extreme FPV pursuit, performing aggressive crash zooms, sharp speed-ramp slowdowns, elastic recoils, 180° and 360° aerial orbits, close turbine flybys, top-down tracking and high-speed undercarriage passes. The McLaren transitions into fast horizontal flight against vivid blue sky and sunlit white clouds. Final cinematic front-left three-quarter hero shot, followed by explosive acceleration as the flying hypercar disappears into the distance. Extreme dynamic editing, realistic mechanical physics, consistent vehicle geometry, natural sunlight, metallic reflections, intense motion blur, turbine roar, pneumatic hissing and powerful cinematic electronic music. No duplicate cars, disappearing wheels, teleportation, magical transformations, extra people, text or overlays.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/mclaren-sky-launch-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "automotive",
      "cgi",
      "mclaren",
      "flight",
      "open-prompt"
    ]
  },
  {
    "id": "aish-ginger-icon-glasses",
    "file": "ginger-icon-glasses",
    "title": "Ginger Icon Glasses",
    "model": "Seedance 2.5",
    "model_slug": "seedance-2-5",
    "type": "video",
    "dur": "0:10",
    "creator": "aish",
    "likes": 1680,
    "date": "сегодня",
    "w": 1280,
    "h": 720,
    "src": "works/ginger-icon-glasses.jpg",
    "video": "works/ginger-icon-glasses.mp4",
    "published": true,
    "prompt": "Create a 10-second vertical 9:16 ultra-photorealistic luxury eyewear CGI commercial following all 28 storyboard frames chronologically. One realistic plush ginger cat with amber eyes and one identical pair of glossy black designer glasses with transparent amber lenses, gold corner ornaments and engraved temples. Preserve exact product geometry and cat anatomy. Pure matte black #080808 background, premium studio lighting, realistic fur and reflections. Extreme physical camera speed ramps, crash zooms, elastic pullbacks, whip pans and 360° orbits. 0–1s: Glasses float centrally; aggressive frontal zoom into amber lens, instant recoil to three-quarter view, rapid orbit revealing gold engraving. 1–2s: Ginger cat appears behind glasses, examines them, tilts head, raises paw and gently touches the frame; glasses drift sideways as camera sweeps laterally. 2–3s: Glasses rotate frontally, open temples and settle naturally onto cat's face; cat blinks, raises chin confidently; rapid 120° orbit reveals eyewear profile. 3–4s: Extreme macro of glossy frame and gold hinge, elastic camera recoil reveals cat's chest and confident expression; cat begins walking forward. 4–5s: Camera tracks backward, whips between left and right profiles, revealing engraved temples; cat stops, lowers head and looks over glasses; dramatic crash zoom. 5–6s: Extreme amber lens-eye macro, rapid pullback, playful head tilt; camera accelerates into a 360° orbit. 6–7s: Complete full-circle orbit, cat raises paw beside face, playfully squints one eye; diagonal beauty push-in. 7–8s: Extreme low-angle hero shot, cat lifts chin; explosive speed-ramp combination: lens crash zoom, elastic recoil, lateral whip, 180° orbit and frontal return. 8–8.6s: Cat sits elegantly, curls tail around paws and faces camera; smooth cinematic push-in. 8.6–10s: Final close-up, cat tilts head slightly, maintains confident eye contact and slowly blinks; gentle push-in ending in a stable hero hold. Keep eyewear consistently prominent and sharply detailed, physically accurate fitting, natural feline movement, seamless spatial continuity and controlled motion blur. Premium funky house 135 BPM, synchronized whooshes, bass hits, subtle paw sounds and final purring. No humans, clothing, props, scenery, text, logos, extra objects, product deformation or digital zooms.",
    "prompt_open": true,
    "refs": [
      {
        "src": "works/ginger-icon-glasses-storyboard.jpg",
        "label": "storyboard"
      }
    ],
    "tags": [
      "eyewear",
      "cgi",
      "cat",
      "luxury",
      "open-prompt"
    ]
  }
];
  extra.forEach(function (w) {
    if (!V.works.some(function (x) { return x.id === w.id; })) V.works.push(w);
  });
  var aish = V.creators.find(function (c) { return c.id === "aish"; });
  if (aish) aish.works = V.works.filter(function (w) { return w.creator === "aish" && w.published !== false; }).length;
})();
