// Загружаем данные о моделях
let models = [];
let selectedModel = null;

// Элементы DOM
const modelCardsContainer = document.getElementById('model-cards');
const promptInput = document.getElementById('prompt-input');
const imageUpload = document.getElementById('image-upload');
const uploadArea = document.getElementById('upload-area');
const uploadedImage = document.getElementById('uploaded-image');
const previewImage = document.getElementById('preview-image');
const removeImageBtn = document.getElementById('remove-image');
const generateBtn = document.getElementById('generate-btn');
const btnText = document.querySelector('.btn-text');
const btnLoading = document.querySelector('.btn-loading');
const resultSection = document.getElementById('result-section');
const resultImage = document.getElementById('result-image');
const downloadBtn = document.getElementById('download-btn');
const regenerateBtn = document.getElementById('regenerate-btn');

// Загружаем модели при загрузке страницы
document.addEventListener('DOMContentLoaded', async () => {
  try {
    // Загружаем все модели с API
    const response = await fetch('http://localhost:5000/api/models?per_page=100');
    const data = await response.json();
    models = data.items;
    
    // Фильтруем только модели для генерации изображений
    const imageModels = models.filter(model => 
      model.tags && model.tags.includes('image-generation')
    );
    
    renderModelCards(imageModels);
    
    // Проверяем, есть ли выбранная модель из localStorage
    const savedModel = localStorage.getItem('selectedModel');
    if (savedModel) {
      try {
        const modelData = JSON.parse(savedModel);
        // Находим модель в списке по vendor/name
        const modelToSelect = imageModels.find(model => 
          model.vendor === modelData.vendor && model.name === modelData.name
        );
        
        if (modelToSelect) {
          // Сразу выбираем модель без задержки
          selectModel(modelToSelect, null);
        } else {
          // Если модель не найдена среди image-generation, показываем её в списке
          console.log('Модель не найдена среди image-generation моделей, добавляем в список');
          imageModels.unshift(modelData);
          renderModelCards(imageModels);
          // Выбираем добавленную модель
          setTimeout(() => {
            const cards = document.querySelectorAll('.model-card');
            const targetCard = cards[0]; // Первая карточка - это наша добавленная модель
            selectModel(modelData, targetCard);
          }, 50);
        }
        // Очищаем localStorage после использования
        localStorage.removeItem('selectedModel');
      } catch (error) {
        console.error('Ошибка парсинга сохраненной модели:', error);
      }
    }
  } catch (error) {
    console.error('Ошибка загрузки моделей:', error);
    modelCardsContainer.innerHTML = '<p>Ошибка загрузки моделей</p>';
  }
});

// Рендеринг карточек моделей
function renderModelCards(modelsToRender) {
  modelCardsContainer.innerHTML = '';
  
  modelsToRender.forEach(model => {
    const card = document.createElement('div');
    card.className = 'model-card';
    card.onclick = () => selectModel(model, card);
    
    card.innerHTML = `
      <img src="${model.image_url || getPlaceholder(model)}" alt="${model.name}" class="model-card-image" onerror="this.src='${getPlaceholder(model)}'">
      <div class="model-card-info">
        <h3>${model.vendor}/${model.name}</h3>
        <p>${model.description || 'Описание недоступно'}</p>
      </div>
    `;
    
    modelCardsContainer.appendChild(card);
  });
}

// Выбор модели
function selectModel(model, cardElement) {
  // Убираем выделение с других карточек
  document.querySelectorAll('.model-card').forEach(card => {
    card.classList.remove('selected');
  });
  
  // Если передана карточка, выделяем её
  if (cardElement) {
    cardElement.classList.add('selected');
  } else {
    // Если карточка не передана, ищем её по модели
    const cards = document.querySelectorAll('.model-card');
    cards.forEach(card => {
      const cardTitle = card.querySelector('h3').textContent;
      if (cardTitle === `${model.vendor}/${model.name}`) {
        card.classList.add('selected');
      }
    });
  }
  
  selectedModel = model;
  
  // Обновляем заголовок страницы с информацией о выбранной модели
  updatePageTitle(model);
  
  console.log('Выбрана модель:', model.name);
}

// Обновление заголовка страницы
function updatePageTitle(model) {
  const heroTitle = document.querySelector('.hero-title');
  const heroSubtitle = document.querySelector('.hero-subtitle');
  
  if (heroTitle && heroSubtitle) {
    heroTitle.innerHTML = `Генерация с <span class="accent">${model.vendor}/${model.name}</span>`;
    heroSubtitle.textContent = model.description || 'Создайте уникальные изображения с помощью выбранной модели';
  }
}

// Placeholder для изображений
function getPlaceholder(model) {
  const placeholders = [
    'https://via.placeholder.com/60x60/6366f1/ffffff?text=AI',
    'https://via.placeholder.com/60x60/8b5cf6/ffffff?text=AI',
    'https://via.placeholder.com/60x60/06b6d4/ffffff?text=AI',
    'https://via.placeholder.com/60x60/10b981/ffffff?text=AI',
    'https://via.placeholder.com/60x60/f59e0b/ffffff?text=AI'
  ];
  
  const index = (model.id || 0) % placeholders.length;
  return placeholders[index];
}

// Обработка загрузки изображения
imageUpload.addEventListener('change', handleImageUpload);

uploadArea.addEventListener('click', () => {
  imageUpload.click();
});

uploadArea.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadArea.classList.add('dragover');
});

uploadArea.addEventListener('dragleave', () => {
  uploadArea.classList.remove('dragover');
});

uploadArea.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadArea.classList.remove('dragover');
  
  const files = e.dataTransfer.files;
  if (files.length > 0) {
    handleImageFile(files[0]);
  }
});

function handleImageUpload(e) {
  const file = e.target.files[0];
  if (file) {
    handleImageFile(file);
  }
}

function handleImageFile(file) {
  if (!file.type.startsWith('image/')) {
    alert('Пожалуйста, выберите файл изображения');
    return;
  }
  
  const reader = new FileReader();
  reader.onload = (e) => {
    previewImage.src = e.target.result;
    uploadArea.style.display = 'none';
    uploadedImage.style.display = 'block';
  };
  reader.readAsDataURL(file);
}

// Удаление загруженного изображения
removeImageBtn.addEventListener('click', () => {
  uploadArea.style.display = 'block';
  uploadedImage.style.display = 'none';
  previewImage.src = '';
  imageUpload.value = '';
});

// Генерация изображения
generateBtn.addEventListener('click', async () => {
  if (!selectedModel) {
    alert('Пожалуйста, выберите модель');
    return;
  }
  
  const prompt = promptInput.value.trim();
  if (!prompt) {
    alert('Пожалуйста, введите описание изображения');
    return;
  }
  
  // Показываем состояние загрузки
  btnText.style.display = 'none';
  btnLoading.style.display = 'flex';
  generateBtn.disabled = true;
  
  try {
    // Здесь будет реальная генерация через API
    // Пока что симулируем процесс
    await simulateGeneration();
    
    // Показываем результат
    showResult();
  } catch (error) {
    console.error('Ошибка генерации:', error);
    alert('Произошла ошибка при генерации изображения');
  } finally {
    // Скрываем состояние загрузки
    btnText.style.display = 'block';
    btnLoading.style.display = 'none';
    generateBtn.disabled = false;
  }
});

// Симуляция генерации (замените на реальный API)
async function simulateGeneration() {
  return new Promise(resolve => {
    setTimeout(resolve, 3000); // 3 секунды симуляции
  });
}

// Показ результата
function showResult() {
  // Создаем placeholder изображение для демонстрации
  const placeholderResult = 'https://via.placeholder.com/512x512/8b5cf6/ffffff?text=Generated+Image';
  
  resultImage.innerHTML = `<img src="${placeholderResult}" alt="Сгенерированное изображение">`;
  resultSection.style.display = 'block';
  
  // Прокручиваем к результату
  resultSection.scrollIntoView({ behavior: 'smooth' });
}

// Скачивание результата
downloadBtn.addEventListener('click', () => {
  const img = resultImage.querySelector('img');
  if (img) {
    const link = document.createElement('a');
    link.href = img.src;
    link.download = `generated-image-${Date.now()}.png`;
    link.click();
  }
});

// Регенерация
regenerateBtn.addEventListener('click', () => {
  generateBtn.click();
});

// Очистка формы
function clearForm() {
  promptInput.value = '';
  uploadArea.style.display = 'block';
  uploadedImage.style.display = 'none';
  previewImage.src = '';
  imageUpload.value = '';
  resultSection.style.display = 'none';
  selectedModel = null;
  document.querySelectorAll('.model-card').forEach(card => {
    card.classList.remove('selected');
  });
}
