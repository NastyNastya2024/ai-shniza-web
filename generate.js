// @ts-nocheck

// Глобальные переменные
let models = [];
let selectedModel = null;
let uploadedFile = null;
let chatHistory = [];

// Загрузка данных при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
  console.log('Страница генерации загружена');
  loadModels();
  initializeEventListeners();
});

// Загрузка моделей
async function loadModels() {
  try {
    console.log('Загружаем модели...');
    const response = await fetch('models.json');
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    models = data.items || data;
    console.log(`Загружено ${models.length} моделей`);
    
    // Загружаем выбранную модель из localStorage
    const savedModelId = localStorage.getItem('selectedModelId');
    if (savedModelId) {
      selectedModel = models.find(model => model.id === savedModelId);
      if (selectedModel) {
        displaySelectedModel();
      }
    }
    
    displayModels();
    
    // Принудительно проверяем скролл после загрузки
    setTimeout(checkScrollAndToggleButton, 100);
  } catch (error) {
    console.error('Ошибка загрузки моделей:', error);
    showError('Ошибка загрузки моделей');
  }
}

// Отображение выбранной модели (упрощенное)
function displaySelectedModel() {
  // Просто логируем выбор модели
  if (selectedModel) {
    console.log('Выбрана модель:', selectedModel.name);
  }
}

// Отображение списка моделей
function displayModels(searchTerm = '') {
  const modelsList = document.getElementById('models-list');
  if (!modelsList) return;
  
  const filteredModels = models.filter(model => 
    model.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (model.description && model.description.toLowerCase().includes(searchTerm.toLowerCase()))
  );
  
  modelsList.innerHTML = filteredModels.map(model => `
    <div class="model-item ${selectedModel && selectedModel.id === model.id ? 'selected' : ''}" 
         data-model-id="${model.id}">
      <div class="model-item-info">
        <h4>${model.name}</h4>
        <p>${model.description || 'Описание недоступно'}</p>
      </div>
    </div>
  `).join('');
  
  // Добавляем обработчики клика
  modelsList.querySelectorAll('.model-item').forEach(item => {
    item.addEventListener('click', () => {
      const modelId = item.dataset.modelId;
      selectModel(modelId);
    });
  });
  
  // Проверяем наличие скролла и показываем/скрываем кнопку переключения
  checkScrollAndToggleButton();
}

// Проверка наличия скролла и управление видимостью кнопки переключения
function checkScrollAndToggleButton() {
  const modelsList = document.getElementById('models-list');
  const modelsToggleBtn = document.getElementById('models-toggle-btn');
  
  if (!modelsList || !modelsToggleBtn) return;
  
  // Проверяем, есть ли скролл
  const hasScroll = modelsList.scrollHeight > modelsList.clientHeight;
  
  // Показываем кнопку только если нет скролла
  if (hasScroll) {
    modelsToggleBtn.style.display = 'none';
  } else {
    modelsToggleBtn.style.display = 'flex';
  }
}

// Отображение моделей в модальном окне
function displayModelsInModal() {
  const modelsModalList = document.getElementById('models-modal-list');
  if (!modelsModalList) return;

  modelsModalList.innerHTML = models.map(model => `
    <div class="model-item ${selectedModel && selectedModel.id === model.id ? 'selected' : ''}" 
         data-model-id="${model.id}">
      <div class="model-item-info">
        <h4>${model.name}</h4>
        <p>${model.description || 'Описание недоступно'}</p>
      </div>
    </div>
  `).join('');
  
  // Добавляем обработчики клика
  modelsModalList.querySelectorAll('.model-item').forEach(item => {
    item.addEventListener('click', () => {
      const modelId = item.dataset.modelId;
      selectModel(modelId);
      // Закрываем модальное окно после выбора
      const modelsModal = document.getElementById('models-modal');
      if (modelsModal) {
        modelsModal.classList.remove('show');
      }
    });
  });
}

// Выбор модели
function selectModel(modelId) {
  selectedModel = models.find(model => model.id === modelId);
  if (!selectedModel) return;
  
  // Сохраняем выбранную модель
  localStorage.setItem('selectedModelId', modelId);
  
  // Обновляем отображение списка
  displayModels(document.getElementById('models-search')?.value || '');
  
  // Добавляем сообщение в чат
  addMessage('assistant', `Выбрана модель: ${selectedModel.name}`);
  
  console.log('Выбрана модель:', selectedModel.name);
}


// Добавление сообщения в чат
function addMessage(sender, content, imageUrl = null) {
  const chatMessages = document.getElementById('chat-messages');
  if (!chatMessages) return;
  
  // Убираем приветственное сообщение если есть
  const welcomeMessage = chatMessages.querySelector('.welcome-message');
  if (welcomeMessage) {
    welcomeMessage.remove();
  }
  
  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${sender}`;
  
  const avatar = sender === 'user' ? 'U' : 'AI';
  const avatarBg = sender === 'user' ? '#8b5cf6' : '#f3f4f6';
  
  let imageHtml = '';
  if (imageUrl) {
    imageHtml = `
      <div class="message-image">
        <img src="${imageUrl}" alt="Сгенерированное изображение">
      </div>
    `;
  }
  
  messageDiv.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-content">
      <div class="message-text">${content}</div>
      ${imageHtml}
    </div>
  `;
  
  chatMessages.appendChild(messageDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  
  // Сохраняем в историю
  chatHistory.push({ sender, content, imageUrl, timestamp: Date.now() });
}

// Инициализация обработчиков событий
function initializeEventListeners() {
  // Поиск моделей
  const searchInput = document.getElementById('models-search');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      displayModels(e.target.value);
    });
  }
  
  // Загрузка файлов
  const fileInput = document.getElementById('image-upload');
  const uploadBtn = document.getElementById('upload-btn');
  const uploadedImage = document.getElementById('uploaded-image');
  const previewImage = document.getElementById('preview-image');
  const removeImage = document.getElementById('remove-image');
  
  if (uploadBtn && fileInput) {
    uploadBtn.addEventListener('click', () => {
      fileInput.click();
    });
  }
  
  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        handleFileUpload(e.target.files[0]);
      }
    });
  }
  
  if (removeImage) {
    removeImage.addEventListener('click', () => {
      uploadedFile = null;
      fileInput.value = '';
      uploadedImage.style.display = 'none';
    });
  }
  
  // Нижняя панель ввода
  const bottomPromptInput = document.getElementById('bottom-prompt-input');
  const sendBtn = document.getElementById('send-btn');
  const attachBtn = document.getElementById('attach-btn');
  
  if (bottomPromptInput) {
    // Автоматическое изменение высоты
    bottomPromptInput.addEventListener('input', (e) => {
      e.target.style.height = 'auto';
      e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
    });
    
    // Enter для отправки
    bottomPromptInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSendMessage();
      }
    });
  }
  
  if (sendBtn) {
    sendBtn.addEventListener('click', handleSendMessage);
  }
  
  if (attachBtn) {
    attachBtn.addEventListener('click', () => {
      fileInput?.click();
    });
  }

  // Модальное окно для моделей на мобильных
  const modelsToggleBtn = document.getElementById('models-toggle-btn');
  const modelsModal = document.getElementById('models-modal');
  const modelsModalClose = document.getElementById('models-modal-close');
  
  if (modelsToggleBtn && modelsModal) {
    modelsToggleBtn.addEventListener('click', () => {
      modelsModal.classList.add('show');
      displayModelsInModal();
    });
  }
  
  if (modelsModalClose && modelsModal) {
    modelsModalClose.addEventListener('click', () => {
      modelsModal.classList.remove('show');
    });
  }
  
  // Закрытие модального окна по клику вне его
  if (modelsModal) {
    modelsModal.addEventListener('click', (e) => {
      if (e.target === modelsModal) {
        modelsModal.classList.remove('show');
      }
    });
  }

  // Проверка скролла при изменении размера окна
  window.addEventListener('resize', checkScrollAndToggleButton);
}

// Обработка загрузки файла
function handleFileUpload(file) {
  if (!file.type.startsWith('image/')) {
    showError('Пожалуйста, выберите изображение');
    return;
  }
  
  uploadedFile = file;
  
  const reader = new FileReader();
  reader.onload = (e) => {
    const previewImage = document.getElementById('preview-image');
    const uploadedImage = document.getElementById('uploaded-image');
    
    if (previewImage) {
      previewImage.src = e.target.result;
    }
    
    if (uploadedImage) {
      uploadedImage.style.display = 'block';
    }
  };
  
  reader.readAsDataURL(file);
}

// Обработка отправки сообщения
async function handleSendMessage() {
  const bottomPromptInput = document.getElementById('bottom-prompt-input');
  const prompt = bottomPromptInput?.value.trim();
  
  if (!prompt) return;
  
  if (!selectedModel) {
    showError('Пожалуйста, выберите модель');
    return;
  }
  
  // Добавляем сообщение пользователя
  addMessage('user', prompt);
  
  // Очищаем поле ввода
  if (bottomPromptInput) {
    bottomPromptInput.value = '';
    bottomPromptInput.style.height = 'auto';
  }
  
  // Показываем индикатор загрузки
  const loadingMessage = addMessage('assistant', 'Генерирую изображение...');
  
  try {
    // Симуляция генерации (замените на реальный API)
    const result = await simulateGeneration(prompt, selectedModel);
    
    // Удаляем сообщение загрузки
    const chatMessages = document.getElementById('chat-messages');
    const lastMessage = chatMessages.lastElementChild;
    if (lastMessage && lastMessage.querySelector('.message-text').textContent === 'Генерирую изображение...') {
      lastMessage.remove();
    }
    
    // Добавляем результат
    addMessage('assistant', `Изображение создано с помощью модели ${selectedModel.name}`, result.imageUrl);
    
  } catch (error) {
    console.error('Ошибка генерации:', error);
    
    // Удаляем сообщение загрузки
    const chatMessages = document.getElementById('chat-messages');
    const lastMessage = chatMessages.lastElementChild;
    if (lastMessage && lastMessage.querySelector('.message-text').textContent === 'Генерирую изображение...') {
      lastMessage.remove();
    }
    
    addMessage('assistant', 'Произошла ошибка при генерации изображения. Попробуйте еще раз.');
  }
}

// Симуляция генерации
async function simulateGeneration(prompt, model) {
  console.log('Генерация изображения:', { prompt, model: model.name });
  
  // Имитируем задержку API
  await new Promise(resolve => setTimeout(resolve, 2000));
  
  // В реальном приложении здесь будет вызов API
  return {
    imageUrl: 'https://via.placeholder.com/512x512?text=Generated+Image',
    prompt: prompt,
    model: model.name
  };
}

// Показ ошибки
function showError(message) {
  // Простое уведомление об ошибке
  alert(message);
}

// Утилиты
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}