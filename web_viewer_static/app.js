const API_BASE = 'http://localhost:5000/api';

let currentChatId = null;
let messages = [];
let allLoadedMessages = []; // Store all loaded messages for searching
let currentPage = 1;
let totalPages = 1;
let isLoading = false;
let allMessagesLoaded = false;
let searchQuery = '';

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    loadChats();
    setupSearch();
    setupEntitiesToggle();
});

// Toggle the per-message entity metadata (hidden by default)
function setupEntitiesToggle() {
    const toggle = document.getElementById('entitiesToggle');
    if (!toggle) return;
    toggle.addEventListener('change', (e) => {
        document.querySelector('.app-container').classList.toggle('show-entities', e.target.checked);
    });
}

// Load list of chats
async function loadChats() {
    const chatList = document.getElementById('chatList');
    chatList.innerHTML = '<div class="loading">Loading chats...</div>';

    try {
        const response = await fetch(`${API_BASE}/chats`);
        const chats = await response.json();

        if (chats.length === 0) {
            chatList.innerHTML = '<div class="loading">No chats found</div>';
            return;
        }

        chatList.innerHTML = '';
        chats.forEach(chat => {
            const chatItem = document.createElement('div');
            chatItem.className = 'chat-item';
            chatItem.innerHTML = `
                <div class="chat-item-name">${escapeHtml(chat.name)}</div>
                <div class="chat-item-meta">${chat.message_count || 0} messages</div>
            `;
            chatItem.addEventListener('click', () => selectChat(chat.id));
            chatList.appendChild(chatItem);
        });
    } catch (error) {
        console.error('Error loading chats:', error);
        chatList.innerHTML = '<div class="loading" style="color: #ff6b6b;">Error loading chats</div>';
    }
}

// Select a chat and load its messages
async function selectChat(chatId) {
    currentChatId = chatId;
    currentPage = 1;
    allMessagesLoaded = false;
    allLoadedMessages = []; // Reset loaded messages
    searchQuery = ''; // Clear search

    // Update active state
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });
    event.target.closest('.chat-item')?.classList.add('active');

    // Show search bar
    document.getElementById('searchBar').style.display = 'flex';
    document.getElementById('searchInput').value = '';
    document.getElementById('searchClear').style.display = 'none';
    document.getElementById('searchResultsInfo').textContent = '';

    // Load chat info
    try {
        const response = await fetch(`${API_BASE}/chats/${chatId}/info`);
        const chatInfo = await response.json();
        updateChatHeader(chatInfo);
    } catch (error) {
        console.error('Error loading chat info:', error);
    }

    // Setup scroll listener
    setupScrollListener();

    // Load initial messages
    await loadMessages(chatId, 1, true);
}

// Load messages for a chat
async function loadMessages(chatId, page = 1, clearContainer = false) {
    if (isLoading || allMessagesLoaded) return;
    
    isLoading = true;
    const messagesContainer = document.getElementById('messagesContainer');
    
    // Show loading indicator only on first load or if clearing
    if (clearContainer) {
        messagesContainer.innerHTML = '<div class="loading">Loading messages...</div>';
    } else {
        // Show loading indicator at bottom
        const loadingDiv = document.createElement('div');
        loadingDiv.id = 'loading-more';
        loadingDiv.className = 'loading';
        loadingDiv.textContent = 'Loading more messages...';
        loadingDiv.style.cssText = 'text-align: center; padding: 20px; color: var(--tg-text-secondary);';
        messagesContainer.appendChild(loadingDiv);
    }

    try {
        const response = await fetch(`${API_BASE}/chats/${chatId}/messages?page=${page}&per_page=100`);
        const data = await response.json();

        // Remove loading indicator
        const loadingEl = document.getElementById('loading-more');
        if (loadingEl) {
            loadingEl.remove();
        }

        if (data.messages && data.messages.length === 0) {
            if (clearContainer) {
                messagesContainer.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><p>No messages found</p></div>';
            }
            allMessagesLoaded = true;
            isLoading = false;
            return;
        }

        // Handle both old format (array) and new format (object with messages)
        const messageList = data.messages || data;
        const pagination = data.pagination;
        
        if (pagination) {
            currentPage = pagination.page;
            totalPages = pagination.pages;
            allMessagesLoaded = currentPage >= totalPages;
        }

        // Store all loaded messages for searching
        allLoadedMessages = allLoadedMessages.concat(messageList);

        if (clearContainer) {
            displayMessages(messageList);
        } else {
            appendMessages(messageList);
        }
        
        // Apply search filter if active
        if (searchQuery) {
            performSearch(searchQuery);
        }
    } catch (error) {
        console.error('Error loading messages:', error);
        if (clearContainer) {
            messagesContainer.innerHTML = '<div class="empty-state"><div class="empty-icon">❌</div><p>Error loading messages</p></div>';
        }
        const loadingEl = document.getElementById('loading-more');
        if (loadingEl) {
            loadingEl.remove();
        }
    } finally {
        isLoading = false;
    }
}

// Display messages (replaces all messages)
function displayMessages(messageList) {
    const messagesContainer = document.getElementById('messagesContainer');
    messagesContainer.innerHTML = '';

    messageList.forEach(message => {
        const messageEl = createMessageElement(message, searchQuery);
        messagesContainer.appendChild(messageEl);
    });

    // Scroll to top (newest messages)
    messagesContainer.scrollTop = 0;
}

// Append messages (for infinite scroll)
function appendMessages(messageList) {
    const messagesContainer = document.getElementById('messagesContainer');
    
    messageList.forEach(message => {
        const messageEl = createMessageElement(message, searchQuery);
        messagesContainer.appendChild(messageEl);
    });
}

// Create message element
function createMessageElement(message, searchQuery = '') {
    const messageDiv = document.createElement('div');
    const isOutgoing = message.outgoing === true;
    messageDiv.className = `message ${isOutgoing ? 'outgoing' : 'incoming'}`;
    
    // Check if message matches search
    const matchesSearch = searchQuery && messageMatchesSearch(message, searchQuery);
    if (matchesSearch) {
        messageDiv.classList.add('highlighted');
    }

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    // Forward info
    if (message.forward_from) {
        const forwardInfo = document.createElement('div');
        forwardInfo.className = 'forward-info';
        const forwardUser = message.forward_from;
        const forwardName = forwardUser.username || forwardUser.first_name || 'Unknown';
        forwardInfo.innerHTML = `<strong>Forwarded from:</strong> ${escapeHtml(forwardName)}`;
        if (message.forward_date) {
            forwardInfo.innerHTML += ` <span style="opacity: 0.7;">(${formatDate(message.forward_date)})</span>`;
        }
        bubble.appendChild(forwardInfo);
    }

    // Message text
    if (message.text) {
        const textDiv = document.createElement('div');
        textDiv.className = 'message-text';
        textDiv.innerHTML = formatMessageText(message.text, message.entities || [], searchQuery);
        bubble.appendChild(textDiv);
    }

    // Message metadata
    const metaDiv = document.createElement('div');
    metaDiv.className = 'message-meta';

    // Sender info
    if (message.from_user && !isOutgoing) {
        const sender = document.createElement('span');
        sender.className = 'message-sender';
        sender.textContent = message.from_user.username || message.from_user.first_name || 'Unknown';
        metaDiv.appendChild(sender);
    }

    // Date
    if (message.date) {
        const date = document.createElement('span');
        date.className = 'message-date';
        date.textContent = formatDate(message.date);
        metaDiv.appendChild(date);
    }

    // Message ID
    if (message.id) {
        const id = document.createElement('span');
        id.className = 'message-id';
        id.textContent = `ID: ${message.id}`;
        metaDiv.appendChild(id);
    }

    bubble.appendChild(metaDiv);

    // Entities info
    if (message.entities && message.entities.length > 0) {
        const entitiesDiv = document.createElement('div');
        entitiesDiv.className = 'message-entities';
        message.entities.forEach(entity => {
            const entityItem = document.createElement('div');
            entityItem.className = 'entity-item';
            entityItem.textContent = `${entity.type}: offset ${entity.offset}, length ${entity.length}`;
            entitiesDiv.appendChild(entityItem);
        });
        bubble.appendChild(entitiesDiv);
    }

    messageDiv.appendChild(bubble);
    return messageDiv;
}

// Format message text with entities and search highlighting
function formatMessageText(text, entities, searchQuery = '') {
    if (!text) return '';
    
    let html = escapeHtml(text);
    
    // Sort entities by offset (reverse to apply from end to start)
    const sortedEntities = [...entities].sort((a, b) => b.offset - a.offset);
    
    sortedEntities.forEach(entity => {
        const start = entity.offset;
        const end = start + entity.length;
        const before = html.substring(0, start);
        const entityText = html.substring(start, end);
        const after = html.substring(end);
        
        let wrapped = entityText;
        if (entity.type === 'MessageEntityType.EMAIL' || entity.type === 'EMAIL') {
            wrapped = `<a href="mailto:${entityText}">${entityText}</a>`;
        } else if (entity.type === 'MessageEntityType.URL' || entity.type === 'URL') {
            wrapped = `<a href="${entityText}" target="_blank" rel="noopener">${entityText}</a>`;
        } else if (entity.type === 'MessageEntityType.TEXT_LINK' || entity.type === 'TEXT_LINK') {
            wrapped = `<a href="${entity.url || entityText}" target="_blank" rel="noopener">${entityText}</a>`;
        } else if (entity.type === 'MessageEntityType.MENTION' || entity.type === 'MENTION') {
            wrapped = `<strong>${entityText}</strong>`;
        } else if (entity.type === 'MessageEntityType.BOLD' || entity.type === 'BOLD') {
            wrapped = `<strong>${entityText}</strong>`;
        } else if (entity.type === 'MessageEntityType.ITALIC' || entity.type === 'ITALIC') {
            wrapped = `<em>${entityText}</em>`;
        } else if (entity.type === 'MessageEntityType.CODE' || entity.type === 'CODE') {
            wrapped = `<code>${entityText}</code>`;
        }
        
        html = before + wrapped + after;
    });
    
    // Apply search highlighting
    if (searchQuery) {
        html = highlightSearchText(html, searchQuery);
    }
    
    return html;
}

// Highlight search text in HTML (preserving existing HTML tags)
function highlightSearchText(html, searchQuery) {
    if (!searchQuery) return html;
    
    const query = escapeHtml(searchQuery).toLowerCase();
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    
    // Split by HTML tags to preserve them
    const parts = html.split(/(<[^>]+>)/);
    return parts.map(part => {
        // Don't highlight inside HTML tags
        if (part.startsWith('<')) {
            return part;
        }
        // Highlight text content
        return part.replace(regex, '<span class="search-highlight">$1</span>');
    }).join('');
}

// Check if message matches search query
function messageMatchesSearch(message, query) {
    if (!query) return false;
    const lowerQuery = query.toLowerCase();
    
    // Search in text
    if (message.text && message.text.toLowerCase().includes(lowerQuery)) {
        return true;
    }
    
    // Search in sender name
    if (message.from_user) {
        const username = message.from_user.username || '';
        const firstName = message.from_user.first_name || '';
        if (username.toLowerCase().includes(lowerQuery) || firstName.toLowerCase().includes(lowerQuery)) {
            return true;
        }
    }
    
    // Search in forwarded from
    if (message.forward_from) {
        const forwardUsername = message.forward_from.username || '';
        const forwardFirstName = message.forward_from.first_name || '';
        if (forwardUsername.toLowerCase().includes(lowerQuery) || forwardFirstName.toLowerCase().includes(lowerQuery)) {
            return true;
        }
    }
    
    return false;
}

// Format date
function formatDate(dateString) {
    if (!dateString) return '';
    
    try {
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return dateString;
        // Always show the date alongside the time (e.g. "Jun 24, 2026, 14:17").
        return date.toLocaleString([], {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    } catch (e) {
        return dateString;
    }
}

// Update chat header
function updateChatHeader(chatInfo) {
    const chatHeader = document.getElementById('chatHeader');
    const firstLetter = chatInfo.name.charAt(0).toUpperCase();
    
    chatHeader.innerHTML = `
        <div class="chat-header-content">
            <div class="chat-header-avatar">${firstLetter}</div>
            <div class="chat-header-info">
                <div class="chat-header-name">${escapeHtml(chatInfo.name)}</div>
                <div class="chat-header-meta">${chatInfo.message_count || 0} messages</div>
            </div>
        </div>
    `;
}

// Setup scroll listener for infinite scroll
function setupScrollListener() {
    const messagesContainer = document.getElementById('messagesContainer');
    
    // Remove existing listener if any
    messagesContainer.onscroll = null;
    
    // Add scroll listener
    messagesContainer.addEventListener('scroll', () => {
        // Don't load more if searching
        if (searchQuery) return;
        
        // Check if near bottom (within 200px)
        const scrollTop = messagesContainer.scrollTop;
        const scrollHeight = messagesContainer.scrollHeight;
        const clientHeight = messagesContainer.clientHeight;
        
        // Load more when within 200px of bottom
        if (scrollHeight - scrollTop - clientHeight < 200) {
            if (!isLoading && !allMessagesLoaded && currentPage < totalPages) {
                loadMessages(currentChatId, currentPage + 1, false);
            }
        }
    });
}

// Setup search functionality
function setupSearch() {
    const searchInput = document.getElementById('searchInput');
    const searchClear = document.getElementById('searchClear');
    const searchResultsInfo = document.getElementById('searchResultsInfo');
    
    let searchTimeout;
    
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.trim();
        searchQuery = query;
        
        // Show/hide clear button
        searchClear.style.display = query ? 'block' : 'none';
        
        // Debounce search
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            performSearch(query);
        }, 300);
    });
    
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            clearSearch();
        }
    });
    
    searchClear.addEventListener('click', () => {
        clearSearch();
    });
}

// Perform search
function performSearch(query) {
    if (!query) {
        // Show all messages
        const messagesContainer = document.getElementById('messagesContainer');
        messagesContainer.innerHTML = '';
        allLoadedMessages.forEach(message => {
            const messageEl = createMessageElement(message, '');
            messagesContainer.appendChild(messageEl);
        });
        document.getElementById('searchResultsInfo').textContent = '';
        return;
    }
    
    // Filter messages
    const filteredMessages = allLoadedMessages.filter(msg => messageMatchesSearch(msg, query));
    
    // Update UI
    const messagesContainer = document.getElementById('messagesContainer');
    messagesContainer.innerHTML = '';
    
    if (filteredMessages.length === 0) {
        messagesContainer.innerHTML = '<div class="empty-state"><div class="empty-icon">🔍</div><p>No messages found matching your search</p></div>';
        document.getElementById('searchResultsInfo').textContent = 'No results';
    } else {
        filteredMessages.forEach(message => {
            const messageEl = createMessageElement(message, query);
            messagesContainer.appendChild(messageEl);
        });
        document.getElementById('searchResultsInfo').textContent = `${filteredMessages.length} result${filteredMessages.length !== 1 ? 's' : ''}`;
    }
}

// Clear search
function clearSearch() {
    const searchInput = document.getElementById('searchInput');
    const searchClear = document.getElementById('searchClear');
    const searchResultsInfo = document.getElementById('searchResultsInfo');
    
    searchInput.value = '';
    searchQuery = '';
    searchClear.style.display = 'none';
    searchResultsInfo.textContent = '';
    
    // Show all messages
    const messagesContainer = document.getElementById('messagesContainer');
    messagesContainer.innerHTML = '';
    allLoadedMessages.forEach(message => {
        const messageEl = createMessageElement(message, '');
        messagesContainer.appendChild(messageEl);
    });
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

