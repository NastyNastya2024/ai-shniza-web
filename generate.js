// @ts-nocheck

// Глобальные переменные
let models = [];
let selectedModel = null;
let uploadedFile = null;
let chatHistory = [];
let replicateAPI = null;

// Загрузка данных при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
  console.log('Страница генерации загружена');
  loadModels();
  initializeEventListeners();
  initializeReplicateAPI();
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
  
  // Убираем проверку на выбранную модель для GPT чата
  
  // Добавляем сообщение пользователя
  addMessage('user', prompt);
  
  // Очищаем поле ввода
  if (bottomPromptInput) {
    bottomPromptInput.value = '';
    bottomPromptInput.style.height = 'auto';
  }
  
  // Показываем индикатор загрузки
  const loadingMessage = addMessage('assistant', 'Думаю над ответом...');
  
  try {
    console.log('Отправка сообщения...');
    console.log('replicateAPI доступен:', !!replicateAPI);
    console.log('CONFIG доступен:', typeof CONFIG !== 'undefined');
    
    if (!replicateAPI) {
      // Fallback если API не загружен
      const chatMessages = document.getElementById('chat-messages');
      const lastMessage = chatMessages.lastElementChild;
      if (lastMessage && lastMessage.querySelector('.message-text').textContent === 'Думаю над ответом...') {
        lastMessage.remove();
      }
      addMessage('assistant', '❌ API не загружен. Проверьте консоль браузера для диагностики.');
      return;
    }
    
    // Подготавливаем системный промпт
    let systemPrompt = "You are a helpful AI assistant for an AI marketplace called '{AI}-шница'. Help users with questions about AI models, image generation, and creative tasks. Respond in Russian.";
    
    if (selectedModel) {
      systemPrompt += ` Currently selected model: ${selectedModel.name}. ${selectedModel.description || ''}`;
    }
    
    console.log('Отправляем запрос к GPT-4o-mini...');
    console.log('Промпт:', prompt);
    console.log('Системный промпт:', systemPrompt);
    
    // Отправляем запрос к GPT-4o-mini
    let response;
    if (uploadedFile) {
      console.log('Отправка с изображением...');
      // Если есть загруженное изображение, конвертируем его в base64
      const imageData = await convertFileToBase64(uploadedFile);
      response = await replicateAPI.sendMessageWithImage(prompt, imageData, systemPrompt);
    } else {
      console.log('Отправка без изображения...');
      response = await replicateAPI.sendMessage(prompt, systemPrompt);
    }
    
    console.log('Получен ответ:', response);
    
    // Удаляем сообщение загрузки и добавляем ответ
    const chatMessages = document.getElementById('chat-messages');
    const lastMessage = chatMessages.lastElementChild;
    if (lastMessage && lastMessage.querySelector('.message-text').textContent === 'Думаю над ответом...') {
      lastMessage.remove();
    }
    
    addMessage('assistant', response);
    
  } catch (error) {
    console.error('Ошибка при отправке запроса:', error);
    
    // Удаляем сообщение загрузки
    const chatMessages = document.getElementById('chat-messages');
    const lastMessage = chatMessages.lastElementChild;
    if (lastMessage && lastMessage.querySelector('.message-text').textContent === 'Думаю над ответом...') {
      lastMessage.remove();
    }
    
    addMessage('assistant', 'Произошла ошибка при обработке запроса. Попробуйте еще раз.');
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

// Инициализация Replicate API
function initializeReplicateAPI() {
  console.log('Инициализация Replicate API...');
  console.log('CONFIG доступен:', typeof CONFIG !== 'undefined');
  console.log('ReplicateAPI доступен:', typeof ReplicateAPI !== 'undefined');
  
  if (typeof CONFIG === 'undefined') {
    console.error('CONFIG не загружен! Проверьте подключение config.js');
    return;
  }
  
  if (typeof ReplicateAPI === 'undefined') {
    console.error('ReplicateAPI не загружен! Проверьте подключение replicate-api.js');
    return;
  }
  
  // Проверяем токен
  if (CONFIG.REPLICATE_API_TOKEN === 'r8_FUA**********************************') {
    console.warn('⚠️ API токен не настроен! Замените токен в config.js');
    addMessage('assistant', '⚠️ API токен не настроен. Пожалуйста, настройте токен в файле config.js');
    return;
  }
  
  replicateAPI = new ReplicateAPI();
  console.log('✅ Replicate API инициализирован успешно');
  console.log('Токен:', CONFIG.REPLICATE_API_TOKEN.substring(0, 10) + '...');
}

// Конвертация файла в base64
function convertFileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
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