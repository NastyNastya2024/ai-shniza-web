# Orb Playground — архитектура

Референс-проект анимированных «орбов» (шариков):  
`~/Downloads/orb-playground` · [github.com/kodgurkini/orb-playground](https://github.com/kodgurkini/orb-playground)

Для {AI}-шницы это **кандидат на визуал шарика** (яишенка на главной / в студии), не часть бэкенда ассистента.

---

## 1. Назначение

Демо-витрина UI-компонентов «orb»:

- несколько цветовых вариантов стеклянного шара;
- режим **talking** (лёгкий scale-pulse);
- отдельный **Universe**-орб со сложными SVG-фильтрами;
- tooltip и shimmer-текст вокруг орба.

Нет API, нет i18n, нет связи с генерацией — только фронтенд-песочница.

---

## 2. Стек

| Слой | Технология |
|------|------------|
| UI | React 19 |
| Язык | TypeScript |
| Сборка | Vite 6 |
| Анимация | [`motion`](https://motion.dev) (`motion/react`) |
| Линт | ESLint 9 + typescript-eslint |

Запуск:

```bash
cd ~/Downloads/orb-playground
npm install   # уже есть node_modules
npm run dev
```

---

## 3. Структура модулей

```
orb-playground/
├── index.html
├── package.json
├── vite.config.ts
├── public/
└── src/
    ├── main.tsx              # React root
    ├── App.tsx               # оболочка «Orb components»
    ├── App.css / index.css
    └── components/
        ├── grid.tsx          # витрина: сетка орбов + dark mode + talking demo
        ├── dynamicOrb.tsx    # ThinkingBall (+ частицы, Airplane SVG)
        ├── universeOrb.tsx   # UniverseOrb (dissolve / noise SVG filters)
        ├── constants.ts      # палитры градиентов / теней по цвету
        ├── tooltip.tsx
        └── shimmerText.tsx
```

### Поток данных (только UI)

```
App
 └─ Grid
     ├─ state: talking, darkMode
     ├─ ThinkingBall × N   ← color, talking?
     ├─ UniverseOrb × 1
     ├─ Tooltip
     └─ constants (стили по color-ключу)
```

Сервер, стор, роутер, контекст ассистента — **отсутствуют**.

---

## 4. Компоненты

### 4.1 `ThinkingBall` (`dynamicOrb.tsx`)

Основной «продуктовый» шар.

| Prop | Тип | Смысл |
|------|-----|--------|
| `color` | `"purple" \| "turquoise" \| "orange" \| "mix" \| "green" \| "gray" \| "ice" \| "white" \| string` | ключ палитры в `constants.ts` |
| `talking` | `boolean` | `scale: 1.075` на spring (имитация «говорит») |
| `m` | `string` | CSS `margin` |

Слои (снизу вверх, упрощённо):

1. Контейнер 82×82, `border-radius: 50%`, фон/тень из `BALL_CONTAINER_STYLES[color]`
2. Overlay / blur / radial / linear градиенты (`OVERLAY_GRADIENT`, `BLUR_GRADIENT`, …)
3. Inner core + dissolve + блики
4. Опционально: частицы (`AnimatePresence`) и SVG «самолётики» (`Airplane`) для живого фона

Анимация: `motion.div` + spring (`stiffness: 650`, `damping: 15`).

### 4.2 `UniverseOrb` (`universeOrb.tsx`)

Отдельный визуальный язык:

- SVG `<filter>` с `feTurbulence` + `feDisplacementMap` (dissolve);
- `useMotionValue` / `animate` для переходов;
- тёмный фон карточки (`#100720` в сетке).

Не использует палитру `constants.ts` ThinkingBall.

### 4.3 `Grid`

Витрина:

- ряд цветов ThinkingBall (purple → ice);
- **Green** — клик/hold включает `talking`;
- **Pearl** — `color="white"`;
- **Universe** — `UniverseOrb`;
- переключатель dark mode для фона карточек.

### 4.4 Вспомогательные

- **Tooltip** — подпись при наведении;
- **ShimmerText** — анимированный текст (рядом с орбом в коммитах «talking mode»).

---

## 5. Система тем (`constants.ts`)

Единый словарь стилей по ключу цвета. Для каждого цвета заданы:

| Константа | Роль |
|-----------|------|
| `BALL_CONTAINER_STYLES` | фон шара + внешняя/внутренняя тень |
| `OVERLAY_GRADIENT` | нижний цветовой оверлей |
| `BLUR_GRADIENT` | блик сверху (с `filter: blur`) |
| `RADIAL_GRADIENT` / `LINEAR_GRADIENT_*` | объём и блики |
| `INNER_CORE` / `DISSOLVE_BACKGROUND` | ядро / растворение |
| `WHITE_GRADIENT` / `BLUE_GRADIENT_*` / `INNER_SHADOW` | дополнительные блики |

Добавить цвет = добавить ключ во все словари (или вынести фабрику палитры).

Ближе всего к яишенке {AI}-шницы по тёплому градиенту: **`orange`** / **`mix`**.

---

## 6. История коммитов (смысл)

| Коммит | Содержание |
|--------|------------|
| first commit | каркас Vite + React |
| Tooltip + shimmerText + Green, Pearl, Universe | набор орбов и обвязка |
| talking mode + darkmode | `talking` prop + тёмные карточки |

Версия в UI: **v0.2**.

---

## 7. Связь с {AI}-шницей

| Orb playground | ai-shniza-web сейчас |
|----------------|----------------------|
| React-компонент | HTML/CSS/JS шарик в `index.html` / `app.html` (orb + глаза + `#speech`) |
| `talking` | набор `index.greet.*` / `studio.eggy.*` + typewriter |
| Палитры в TS | CSS variables / inline gradient на героя |
| Нет API | `/api/assistant/chat`, generate, i18n |

Фразы облачка задокументированы отдельно: [`../index-orb-phrases.md`](../index-orb-phrases.md).

### Возможный путь интеграции (не сделано)

1. Выбрать орб: `ThinkingBall` color=`orange`|`mix` (± talking).
2. Собрать как изолированный виджет (Vite library / скопировать CSS-слои без React, если оставляем vanilla `app.html`).
3. Прокинуть `talking={typing || speaking}` из студии / главной.
4. Не тащить UniverseOrb на первый экран без необходимости (тяжелее по фильтрам).

---

## 8. Границы ответственности

**Входит в playground:** визуал, анимация, демо-сетка.

**Не входит:** промпты, LLM, цены, модели, cookie сессий, i18n, SSR.

---

## 9. Риски при переносе в продукт

- React 19 + Motion — новый стек относительно текущего static HTML студии.
- Много inline-стилей и дублирование палитр — нужна нормализация под `--accent` сайта.
- SVG dissolve (Universe) может быть дорогим на мобильных.
- Лицензия/происхождение: внешний репозиторий `kodgurkini` — перед продакшеном проверить лицензию и атрибуцию.
