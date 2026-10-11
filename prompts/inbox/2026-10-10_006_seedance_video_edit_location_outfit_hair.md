# inbox dump- date: 2026-10-10- note: PDF «Промпт для смены локации, одежды и причёски» · Seedance 2.5 Video Edit (9 pages) — full extract- source_pdf: 2026-10-10_006_seedance_video_edit_location_outfit_hair.pdf- status: unstructured---
## PAGE 1/9

Промпт
ДЛЯ СМЕНЫ
ЛОКАЦИИ,
ОДЕЖДЫ И
ПРИЧЁСКИ
SEEDANCE 2.5 · VIDEO EDIT
VIDEO 1
IMAGE 1
IMAGE 2
Исходное видео + outfit reference + hairstyle reference
Локация в этом кейсе задаётся текстом внутри промпта.
1

## PAGE 2/9

Референсы
ЧТО ЗАГРУЗИТЬ
2
В этом примере мы работаем в Seedance 2.5 · Video Edit. Важно сохранить порядок файлов: обозначения Video
1 / Image 1 / Image 2 в интерфейсе должны совпадать с ролями в промпте.
VIDEO 1
База: лицо, мимика, речь,
движения, посадка, ракурс,
крупность и композиция.
IMAGE 1
Берём только одежду. Не берём
фон или любые другие элементы
изображения.
IMAGE 2
Берём только причёску. Не берём
лицо, кожу, фигуру, одежду или
фон.
ЛОКАЦИЯ
Отдельную картинку локации в Seedance не загружаем. Интерьер описан словами внутри блока CHANGE, чтобы
новая среда адаптировалась под исходную перспективу и посадку из Video 1.
Важно
План, ракурс, композиция и крупность исходного видео не меняются. Нейросеть должна заменить
только заданные элементы внутри существующего видео, а не пересобрать сцену заново.
Кресло из исходного видео тоже не используется: в новой локации появляется новое дизайнерское кресло, но оно
подстраивается под уже существующую посадку и положение рук.

## PAGE 3/9

Методология
КАК УСТРОЕН EDIT-ПРОМПТ
3
Я разделяю Edit-промпт на смысловые блоки, чтобы нейросеть чётко понимала: что является базой, что
нужно сохранить, что заменить, как встроить изменение и что категорически нельзя трогать.
1
BASE
Video 1 остаётся основой. Мы редактируем готовое видео, а не создаём новое.
2
REFERENCE ROLES
Заранее фиксируем, за что отвечает каждый файл: outfit, hairstyle и т.д.
3
KEEP
Лицо, мимика, речь, тайминг, посадка, камера, крупность, ракурс и композиция остаются исходными.
4
CHANGE + INTEGRATION
Меняем только нужные элементы и заставляем новую локацию / одежду / причёску физически встроиться в
исходный кадр.
5
CONSTRAINTS
Повторно фиксируем запреты: без zoom, reframe, face drift, лишних объектов и смены композиции.
Подсказка
Для первого теста не перегружайте промпт дополнительными изменениями. Чем точнее распределены роли
референсов и ограничения, тем проще модели сохранить исходную камеру и человека.

## PAGE 4/9

Промпт
ЧАСТЬ 1 · BASE / REFERENCES / KEEP
4
Use @[Video 1](video_1) as the direct base source video and edit strictly inside this original video. Do not create a
new video from scratch. Keep the original format, duration, timing and speaking performance exactly the same.
REFERENCE ROLES
@[Video 1](video_1) - base source video to edit.
@[Image 1](image_1) - outfit reference only.
@[Image 2](image_2) - hairstyle reference only.
WHAT TO TAKE FROM EACH REFERENCE
Use @[Image 1](image_1) only for the outfit: a soft pink satin tailored top / blazer-style upper garment with a deep
V neckline, long sleeves, a high neck band detail and long scarf-like draped front panels. The fabric should look
silky, luminous and elegant, with a refined satin sheen.
Use @[Image 2](image_2) only for the hairstyle: long, sleek, smooth straight hair with a clean center part, falling
evenly past the shoulders. Take only the hairstyle. Do not take the face, identity, skin, body, clothing or background
from this reference.
KEEP
Keep the original woman from @[Video 1](video_1) fully recognizable and preserve her exact identity, facial
features, facial anatomy, natural skin texture, body proportions, expression flow, lip-sync, speech, gestures, timing,
pose logic and performance.
Keep the original camera setup exactly the same: same shot size, same framing, same crop, same composition,
same perspective, same camera angle, same camera distance, same lens feel, same timing, same duration.
Do not widen the shot. Do not zoom out. Do not zoom in. Do not reframe. Do not change the shot scale or
composition in any way. Do not reveal more of the body than is already visible in @[Video 1](video_1). Do not show
the legs if they are not visible in the original video. Do not reveal more of the outfit than the original framing allows.
Keep the original speaking action exactly as it is.
Do not use the outfit, hairstyle or chair from @[Video 1](video_1).

## PAGE 5/9

Промпт
ЧАСТЬ 2 · CHANGE / LOCATION
5
CHANGE
Replace the original environment with a sophisticated contemporary interior with a calm, premium, understated
luxury aesthetic.
LOCATION
The space should feel warm, architectural and highly refined, with a restrained palette of warm browns,
taupe-beige neutrals, muted charcoal accents and soft stone-gray flooring.
The interior should combine large floor-to-ceiling walnut wood wall panels in a rich medium-to-dark walnut tone,
with a fine elegant grain, clean vertical seams, and a smooth matte or satin finish.
Adjacent wall surfaces should be soft warm greige or taupe-beige with a subtle plaster-like, mineral softness,
smooth and luxurious rather than stark white.
The flooring should be large-format matte stone or porcelain tiles in a muted warm gray / greige tone,
contemporary and minimal, with very little visual noise.
Part of the space should include a soft light neutral rug in pale beige or warm off-white, with a subtle woven texture
that softens the harder architectural materials.
A key element of the new location must be a sculptural lounge armchair. This chair should fully replace the chair
from @[Video 1](video_1).
The new armchair should be upholstered in smooth caramel-brown leather with a rich cognac-to-chestnut tone.
The leather should look refined, premium and tactile, with a matte or softly satin finish.
The chair should have a low, wide, grounded silhouette, broad curved arm sections, rounded continuous lines, a
deep comfortable seat, and a gently curved integrated backrest. It should feel like a modern designer statement
piece: sculptural, minimal, elegant and luxurious.
IMPORTANT: If the woman is resting her hands or arms as in the original video, the new chair must support that
same natural arm placement and seated posture. Do not change her seated pose to fit the chair. Do not move her
hands or arms to accommodate the new furniture. Instead, adapt the new chair around her exact original seated
posture and interaction from @[Video 1](video_1), so it looks like she was naturally filmed sitting in this new
armchair.
Add a small cylindrical accent side table beside the chair. The table should be made of dark reddish-brown polished
natural stone or marble, with subtle veining and a rich burgundy-brown / mahogany tone. It should feel compact,
solid, minimal and luxurious.
Place a simple clear drinking glass on the side table.

## PAGE 6/9

Промпт
ЧАСТЬ 3 · LOCATION / WARDROBE / LIGHT
6
Add a tall sculptural contemporary floor lamp with a slim tapering matte black base, a clean geometric silhouette,
and a large flat circular top. It should read as a minimalist architectural design object.
Include a large window or full-height glazing that brings in soft natural daylight. The window should have
full-length curtains in a soft warm off-white / ivory / light beige tone. The curtains should be elegant, understated
and smooth, adding softness to the space without becoming visually dominant.
WARDROBE / HAIR
Dress the woman in the pink satin outfit from @[Image 1](image_1) only.
Give her the hairstyle from @[Image 2](image_2) only.
Do not take any clothing from @[Video 1](video_1). Do not take any hairstyle from @[Video 1](video_1).
LIGHTING / FACE LIGHTING / ATMOSPHERE
The woman's face must be evenly and softly illuminated, with flattering smooth light and no harsh deep shadows
across the face.
The room should be lit with a combination of soft natural daylight from the window and controlled ambient interior
light.
The lighting should feel soft, diffused, refined, warm-neutral, clean, premium, and editorial.
No aggressive highlights. No hard direct sunlight. No dramatic contrast. No deep heavy shadows.
The wood, leather and stone materials should receive subtle natural highlights that reveal texture without
becoming glossy or overlit.
The overall atmosphere should feel quiet luxury, contemporary minimalism, calm, editorial, intimate, sophisticated,
and photorealistic.

## PAGE 7/9

Промпт
ЧАСТЬ 4 · INTEGRATION / CONSTRAINTS
7
HOW TO INTEGRATE THE CHANGE
All changes must be integrated naturally into the original video so it looks as if the woman was originally filmed in
this luxury interior.
The environment must adapt to the exact existing framing of @[Video 1](video_1), not the other way around.
The woman must remain in the same position, same crop and same shot size as in the original video.
The new outfit must fit naturally on her visible body area only, with realistic satin texture, folds, highlights and
fabric behavior.
The hairstyle must feel naturally attached and realistic.
The new chair must seamlessly replace the original chair while preserving her natural seated interaction and arm
support.
CONSTRAINTS
Do not change the original woman's identity, face, facial anatomy, body proportions, lip-sync, expression timing,
gestures or speaking performance.
Do not change the original shot size, framing, crop, composition, camera angle, perspective, camera distance,
movement, timing or duration.
Do not zoom out. Do not zoom in. Do not widen the frame. Do not reframe. Do not restage the scene. Do not reveal
the legs. Do not reveal more of the outfit than the original framing allows.
Do not use the outfit from @[Video 1](video_1). Do not use the hairstyle from @[Video 1](video_1). Do not use the
chair design from @[Video 1](video_1).
Do not take facial features, identity or body information from @[Image 2](image_2).
Do not take background from any reference image.
Do not beautify the skin excessively. Do not remove natural skin texture. Do not create plastic skin.
No face drift. No anatomy distortion. No warped hands. No deformed clothing. No unstable hair. No flickering
objects. No background warping. No extra people. No random objects.
Everything must remain stable, elegant, photorealistic and seamlessly integrated inside the exact visible
boundaries of @[Video 1](video_1).

## PAGE 8/9

Практика
КАК ЗАГРУЗИТЬ В SEEDANCE 2.5 EDIT
8
1
Откройте Video  Seedance 2.5  Edit.
2
Загрузите файлы в том же порядке, под который написан промпт: Video 1  Image 1  Image 2.
3
Проверьте, что длительность и соотношение сторон совпадают с исходным видео.
4
Вставьте промпт целиком. Не меняйте номера референсов внутри текста.
5
Для первого теста можно начать с 720p, если этот режим доступен в вашем аккаунте. После
удачного результата при необходимости повторить генерацию в более высоком качестве.
6
Нажмите Generate и оценивайте не только одежду / волосы, но и стабильность лица, крупности,
камеры и контакта рук с новым креслом.
Проверка перед Generate
Video 1 = база · Image 1 = одежда · Image 2 = причёска · локация = текст. Камера / план / ракурс / композиция
остаются из Video 1.

## PAGE 9/9

Бонус
HIGGSFIELD
По моей партнёрской ссылке Higgsfield может показать
персональную скидку до 50%, активную в течение 3 часов после
входа по ссылке.
ПАРТНЁРСКАЯ ССЫЛКА
https://higgsfield.ai?fpr=svetlana-be20ad
Важно про цену: конкретный размер скидки и доступные тарифы могут отличаться в зависимости от оффера,
региона и аккаунта.
Официально Higgsfield указывает: referral-скидка может составлять до 50% и действует 3 часа. Стандартная
цена Ultra на публичной странице Higgsfield сейчас указана как $129/мес.
Если по вашей ссылке Ultra отображается как 129  99, воспринимайте это как персональное
промо-предложение: валюта и размер скидки могут отличаться. Перед оплатой обязательно проверьте
итоговую цену, срок действия предложения и цену следующего продления.
Условия affiliate-программы: higgsfield.ai/affiliate
Актуальные цены и условия могут меняться.
Сохраняйте структуру — меняйте только свои референсы.
9
