/**
 * Centralized LLM Platform - Widget SDK
 * JavaScript client for embedding the chatbot widget on customer websites
 */

(function() {
    const LLMChatbot = {
        // Configuration
        config: {
            apiUrl: null,
            tenantId: null,
            authToken: null,
            tokenExpiresAt: null,
            sessionId: null,
            tenantConfig: null,
            _cachedMessages: null,
            theme: {
                primaryColor: '#3b82f6',
                backgroundColor: '#ffffff',
                textColor: '#1f2937'
            },
            position: {
                bottom: '20px',
                right: '20px',
                left: 'auto',
                top: 'auto'
            }
        },

        // Initialize widget
        init: async function(options) {
            // Prevent duplicate initialization - widget already exists
            if (document.getElementById('llm-chatbot-widget')) {
                console.log('LLMChatbot: Widget already initialized, ensuring visibility');
                const widget = document.getElementById('llm-chatbot-widget');
                const launcherWrap = document.getElementById('llm-launcher-wrap');
                // Ensure launcher is visible, widget is hidden
                if (widget) widget.style.display = 'none';
                if (launcherWrap) launcherWrap.style.display = 'flex';
                // Load previous conversation if session exists
                const storedSession = this._loadStoredSessionId();
                if (storedSession) {
                    this.config.sessionId = storedSession;
                    // Fetch messages from server and display
                    this._fetchAndDisplayConversation(storedSession);
                }
                return;
            }

            // Merge options with config
            Object.assign(this.config, options);

            // Keep one session per browser+tenant unless explicitly overridden.
            if (!this.config.sessionId && this.config.tenantId) {
                const stored = this._loadStoredSessionId();
                if (stored) {
                    this.config.sessionId = stored;
                }
            }
            
            if (!this.config.tenantId) {
                console.error('LLMChatbot: tenantId is required');
                return;
            }

            // Schedule automatic token refresh
            this._scheduleTokenRefresh();

            // Fetch tenant configuration
            await this.fetchTenantConfig();

            // Validate stored session — restore lead state or clear stale data
            await this._validateStoredSession();

            // Create widget container
            this.createWidget();
            this.attachEventListeners();
            // Load previous conversation if any exists
            this._loadPreviousConversation();
            console.log('LLMChatbot: Initialized for tenant', this.config.tenantId);
        },

        // Validate stored session on init — sync lead state with server
        _validateStoredSession: async function() {
            const sessionId = this.config.sessionId;
            if (!sessionId) return;
            try {
                const res = await fetch(
                    `${this.config.apiUrl}/api/chat/session/${sessionId}`,
                    { headers: { 'Content-Type': 'application/json' } }
                );
                if (res.status === 404 || res.status === 422) {
                    // Session expired or not found — clear stale localStorage
                    this.config.sessionId = null;
                    try {
                        localStorage.removeItem(this._sessionStorageKey());
                        localStorage.removeItem(`llm_lead_${this.config.tenantId || 'default'}`);
                        localStorage.removeItem(`llm_msg_count_${this.config.tenantId || 'default'}`);
                    } catch(e) {}
                    return;
                }
                if (!res.ok) return;
                const messages = await res.json();
                // Store messages for later display
                this.config._cachedMessages = messages;
                // If session has messages, check if lead was already collected
                if (Array.isArray(messages) && messages.length > 0) {
                    const userMsgs = messages.filter(m => m.role === 'user');
                    if (userMsgs.length >= 3) {
                        this._saveLeadCollected(true);
                    }
                }
            } catch(e) {
                // Network error — don't change state
            }
        },

        // Load previous conversation from cached messages
        _loadPreviousConversation: function() {
            if (!this.config._cachedMessages || !Array.isArray(this.config._cachedMessages)) return;
            const messagesDiv = document.getElementById('llm-messages');
            if (!messagesDiv) return;
            // Clear any welcome message
            messagesDiv.innerHTML = '';
            // Display all previous messages (addMessageToUI auto-scrolls to bottom)
            this.config._cachedMessages.forEach(msg => {
                if (msg.role && msg.content) {
                    this.addMessageToUI(msg.content, msg.role, msg.id);
                }
            });
            this.config._cachedMessages = null; // Clear cache after loading
            // Focus the input field
            setTimeout(() => {
                const input = document.getElementById('llm-message-input');
                if (input) input.focus();
            }, 100);
        },

        // Fetch conversation from server and display
        _fetchAndDisplayConversation: async function(sessionId) {
            if (!sessionId || !this.config.apiUrl) return;
            const messagesDiv = document.getElementById('llm-messages');
            if (!messagesDiv) return;
            
            // Show loading indicator
            const loadingDiv = document.createElement('div');
            loadingDiv.id = 'llm-loading-msg';
            loadingDiv.className = 'llm-message llm-loading';
            loadingDiv.textContent = '💬 Loading conversation...';
            loadingDiv.style.fontStyle = 'italic';
            loadingDiv.style.color = '#6b7280';
            loadingDiv.style.background = '#f3f4f6';
            messagesDiv.appendChild(loadingDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            
            try {
                const res = await fetch(
                    `${this.config.apiUrl}/api/chat/session/${sessionId}`,
                    { headers: { 'Content-Type': 'application/json' } }
                );
                // Remove loading indicator
                if (loadingDiv.parentNode) loadingDiv.remove();
                
                if (res.ok) {
                    const messages = await res.json();
                    if (Array.isArray(messages) && messages.length > 0) {
                        messagesDiv.innerHTML = '';
                        messages.forEach(msg => {
                            if (msg.role && msg.content) {
                                this.addMessageToUI(msg.content, msg.role, msg.id);
                            }
                        });
                    }
                }
            } catch(e) {
                if (loadingDiv.parentNode) loadingDiv.remove();
            }
            // Focus input after loading
            setTimeout(() => {
                const input = document.getElementById('llm-message-input');
                if (input) input.focus();
            }, 100);
        },

        // Schedule automatic token refresh - runs every 12 minutes
        _scheduleTokenRefresh: function() {
            const refreshInterval = 12 * 60 * 1000; // 12 minutes
            const self = this;
            
            // Immediate token fetch on init
            if (self.config.tokenRefreshUrl) {
                self._fetchToken();
            }
            
            setInterval(async () => {
                if (self.config.tokenRefreshUrl) {
                    self._fetchToken();
                }
            }, refreshInterval);
        },

        _fetchToken: async function() {
            try {
                const response = await fetch(this.config.tokenRefreshUrl, {
                    credentials: 'include',
                    headers: { 'Accept': 'application/json' }
                });
                if (!response.ok) return;
                const contentType = response.headers.get('content-type') || '';
                if (!contentType.includes('application/json')) {
                    // Endpoint returned HTML (404/redirect) — silently skip,
                    // the token refresh URL is not configured correctly.
                    return;
                }
                const data = await response.json();
                if (data && data.token) {
                    this.config.authToken = data.token;
                    this.config.tokenExpiresAt = data.expires_at ? new Date(data.expires_at) : null;
                }
            } catch (_) {
                // Network error — silently skip, will retry on next interval.
            }
        },

        // Fetch tenant configuration from backend
        fetchTenantConfig: async function() {
            try {
                const response = await fetch(`${this.config.apiUrl}/api/tenants/${this.config.tenantId}/config`);
                if (response.ok) {
                    this.config.tenantConfig = await response.json();
                }
            } catch (error) {
                console.warn('LLMChatbot: Could not fetch tenant config', error);
            }
        },

        // Create widget DOM
        createWidget: function() {
            // Check if widget already exists
            if (document.getElementById('llm-chatbot-widget')) return;


            const style = `
                #llm-chatbot-widget {
                    position: fixed;
                    bottom: calc(${this.config.position.bottom} + 70px);
                    right: ${this.config.position.right};
                    left: ${this.config.position.left};
                    top: ${this.config.position.top};
                    width: 400px;
                    height: 580px;
                    max-width: 98vw;
                    max-height: 92vh;
                    border-radius: 16px;
                    box-shadow: 0 12px 40px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.08);
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    z-index: 9999;
                    display: flex;
                    flex-direction: column;
                    animation: llm-slide-up 0.22s ease;
                }

                @keyframes llm-slide-up {
                    from { opacity: 0; transform: translateY(16px); }
                    to   { opacity: 1; transform: translateY(0); }
                }

                .llm-typing-dots {
                    display: inline-flex;
                    gap: 4px;
                }
                .llm-typing-dots span {
                    animation: llm-typing-bounce 1.4s infinite ease-in-out both;
                    font-size: 18px;
                    font-weight: bold;
                    color: #6b7280;
                }
                .llm-typing-dots span:nth-child(1) { animation-delay: -0.32s; }
                .llm-typing-dots span:nth-child(2) { animation-delay: -0.16s; }
                @keyframes llm-typing-bounce {
                    0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
                    40% { transform: scale(1); opacity: 1; }
                }

                /* Responsive for tablets */
                @media (max-width: 900px) {
                    #llm-chatbot-widget {
                        width: 95vw;
                        height: 85vh;
                        min-width: 220px;
                        min-height: 220px;
                    }
                    #llm-inline-lead-form {
                        padding: 10px 10px !important;
                    }
                }

                /* Responsive for mobile */
                @media (max-width: 600px) {
                    #llm-chatbot-widget {
                        width: 100vw !important;
                        height: 100vh !important;
                        min-width: 0 !important;
                        min-height: 0 !important;
                        border-radius: 0 !important;
                        right: 0 !important;
                        left: 0 !important;
                        bottom: 0 !important;
                        top: 0 !important;
                        max-height: 100vh !important;
                        max-width: 100vw !important;
                    }
                    .llm-chat-container {
                        height: 100% !important;
                        max-height: 100% !important;
                        border-radius: 0 !important;
                    }
                    .llm-chat-messages {
                        flex: 1 1 auto !important;
                        max-height: none !important;
                        overflow-y: auto !important;
                    }
                    /* Lead collection form - mobile responsive */
                    .llm-lead-form {
                        width: 100% !important;
                        max-width: 100% !important;
                        min-width: 0 !important;
                        margin: 0 !important;
                        padding: 16px !important;
                        border-radius: 0 !important;
                        box-shadow: none !important;
                        box-sizing: border-box !important;
                        overflow-y: auto !important;
                        max-height: 100% !important;
                    }
                    #llm-inline-lead-form {
                        padding: 9px 10px !important;
                        border-radius: 8px !important;
                        width: 100% !important;
                        max-width: 100% !important;
                        box-sizing: border-box !important;
                    }
                    #llm-inline-lead-form input {
                        font-size: 14px !important;
                        padding: 7px 2px !important;
                    }
                    #llm-inline-lead-form button {
                        font-size: 13px !important;
                        min-height: 36px !important;
                        width: auto !important;
                    }
                    .llm-lead-form h3 {
                        font-size: 16px !important;
                        margin-bottom: 8px !important;
                    }
                    .llm-lead-form .form-subtitle {
                        font-size: 13px !important;
                        margin-bottom: 16px !important;
                    }
                    .llm-lead-form .form-group {
                        margin-bottom: 12px !important;
                    }
                    .llm-lead-form label {
                        font-size: 13px !important;
                        margin-bottom: 6px !important;
                    }
                    .llm-lead-form input {
                        width: 100% !important;
                        min-width: 0 !important;
                        padding: 14px 16px !important;
                        font-size: 16px !important;
                        border-radius: 10px !important;
                        box-sizing: border-box !important;
                    }
                    .llm-lead-form button[type="submit"] {
                        width: 100% !important;
                        min-width: 0 !important;
                        padding: 16px !important;
                        font-size: 16px !important;
                        border-radius: 10px !important;
                        margin-top: 16px !important;
                        min-height: 52px !important;
                    }
                    .llm-lead-form .skip-link {
                        font-size: 14px !important;
                        padding: 10px !important;
                        margin-top: 12px !important;
                    }
                    /* Chat input area */
                    .llm-chat-input {
                        padding: 10px 12px !important;
                    }
                    .llm-chat-input input {
                        font-size: 15px !important;
                        padding: 10px 14px !important;
                        border-radius: 24px !important;
                        width: auto !important;
                        min-width: 0 !important;
                    }
                    .llm-chat-input button {
                        font-size: 18px !important;
                        width: 42px !important;
                        height: 42px !important;
                        min-height: 42px !important;
                        padding: 0 !important;
                        border-radius: 50% !important;
                        flex-shrink: 0 !important;
                    }
                    /* Messages */
                    .llm-message {
                        max-width: 85% !important;
                        font-size: 15px !important;
                        padding: 12px 16px !important;
                    }
                    .llm-chat-header {
                        padding: 14px 16px !important;
                    }
                    .llm-chat-header span {
                        font-size: 17px !important;
                    }
                    .llm-close-btn {
                        font-size: 24px !important;
                    }
                }

                .llm-chat-container {
                    display: flex;
                    flex-direction: column;
                    height: 100%;
                    background: ${this.config.theme.backgroundColor};
                    border-radius: 16px;
                    overflow: hidden;
                }

                .llm-chat-header {
                    background: linear-gradient(135deg, ${this.config.theme.primaryColor} 0%, color-mix(in srgb, ${this.config.theme.primaryColor} 70%, #000) 100%);
                    color: white;
                    padding: 14px 18px;
                    font-weight: 600;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 10px;
                    border-radius: 12px 12px 0 0;
                }

                .llm-header-left {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }

                .llm-header-avatar {
                    width: 36px;
                    height: 36px;
                    border-radius: 50%;
                    background: rgba(255,255,255,0.18);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                    padding: 4px;
                    box-sizing: border-box;
                }

                .llm-header-info {
                    display: flex;
                    flex-direction: column;
                    gap: 2px;
                }

                .llm-header-name {
                    font-size: 15px;
                    font-weight: 700;
                    line-height: 1.2;
                }

                .llm-header-status {
                    font-size: 11px;
                    font-weight: 400;
                    opacity: 0.85;
                    display: flex;
                    align-items: center;
                    gap: 4px;
                }

                .llm-status-dot {
                    width: 7px;
                    height: 7px;
                    background: #4ade80;
                    border-radius: 50%;
                    display: inline-block;
                }

                .llm-chat-messages {
                    flex: 1;
                    overflow-y: auto;
                    padding: 16px;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }

                .llm-message {
                    max-width: 82%;
                    padding: 10px 14px;
                    border-radius: 14px;
                    word-wrap: break-word;
                    white-space: pre-line;
                    font-size: 14px;
                    line-height: 1.5;
                }

                .llm-message.user {
                    align-self: flex-end;
                    background: ${this.config.theme.primaryColor};
                    color: white;
                }

                .llm-message.assistant {
                    align-self: flex-start;
                    background: #f3f4f6;
                    color: ${this.config.theme.textColor};
                    border: 1px solid #e5e7eb;
                }

                .llm-feedback {
                    margin-top: 6px;
                    display: flex;
                    gap: 6px;
                    justify-content: flex-end;
                }

                /* Responsive quick contact form inside widget */
                .llm-chat-container form, .quick-contact-form {
                    width: 100% !important;
                    max-width: 100% !important;
                    box-sizing: border-box;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }
                .llm-chat-container input:not(#llm-message-input),
                .llm-chat-container button:not(#llm-send-btn):not(.llm-close-btn):not(.llm-feedback-btn),
                .quick-contact-form input,
                .quick-contact-form button {
                    width: 100% !important;
                    min-width: 0 !important;
                    box-sizing: border-box;
                }
                #llm-message-input {
                    box-sizing: border-box;
                }
                .llm-chat-container .quick-contact-form {
                    overflow-y: auto;
                    max-height: 60vh;
                }

                .llm-feedback-btn {
                    border: 1px solid #d1d5db;
                    background: #ffffff;
                    border-radius: 6px;
                    cursor: pointer;
                    padding: 2px 8px;
                    font-size: 13px;
                }

                .llm-feedback-btn.active {
                    border-color: ${this.config.theme.primaryColor};
                    color: ${this.config.theme.primaryColor};
                }
                
                .llm-chat-input {
                    padding: 10px 12px;
                    border-top: 1px solid #e5e7eb;
                    display: flex;
                    flex-direction: row;
                    gap: 8px;
                    align-items: center;
                    background: #f9fafb;
                    flex-wrap: nowrap;
                }

                .llm-chat-input input {
                    flex: 1 1 0;
                    min-width: 0;
                    width: 0;
                    border: 1.5px solid #d1d5db;
                    border-radius: 22px;
                    padding: 9px 14px;
                    font-size: 14px;
                    outline: none;
                    background: #fff;
                    color: #111827;
                    transition: border-color 0.15s;
                    box-sizing: border-box;
                }

                .llm-chat-input input::placeholder {
                    color: #9ca3af;
                }

                .llm-chat-input input:focus {
                    border-color: ${this.config.theme.primaryColor};
                    box-shadow: 0 0 0 3px ${this.config.theme.primaryColor}22;
                }

                .llm-chat-input button {
                    flex: 0 0 40px;
                    width: 40px;
                    height: 40px;
                    border-radius: 50%;
                    background: ${this.config.theme.primaryColor};
                    color: white;
                    border: none;
                    cursor: pointer;
                    font-size: 17px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: transform 0.15s, opacity 0.15s;
                    box-shadow: 0 2px 8px ${this.config.theme.primaryColor}55;
                }

                .llm-chat-input button:hover {
                    opacity: 0.88;
                    transform: scale(1.08);
                }
                
                /* ── Launcher button ── */
                .llm-launcher-wrap {
                    position: fixed;
                    bottom: ${this.config.position.bottom};
                    right: ${this.config.position.right};
                    left: ${this.config.position.left};
                    top: ${this.config.position.top};
                    z-index: 9998;
                    display: flex;
                    flex-direction: column;
                    align-items: flex-end;
                    gap: 8px;
                }

                .llm-tooltip {
                    background: linear-gradient(135deg, ${this.config.theme.primaryColor} 0%, #1f2937 100%);
                    color: #fff;
                    font-size: 13px;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    padding: 8px 16px;
                    border-radius: 20px;
                    white-space: nowrap;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.25), 0 0 15px ${this.config.theme.primaryColor}30;
                    opacity: 0;
                    transform: translateY(6px) scale(0.9);
                    transition: opacity 0.25s, transform 0.25s;
                    pointer-events: none;
                    position: relative;
                    animation: llm-tooltip-bounce 0.5s ease-out;
                }

                @keyframes llm-tooltip-bounce {
                    0% { transform: translateY(6px) scale(0.8); opacity: 0; }
                    60% { transform: translateY(-3px) scale(1.05); }
                    100% { transform: translateY(0) scale(1); opacity: 1; }
                }
                .llm-tooltip::after {
                    content: '';
                    position: absolute;
                    bottom: -6px;
                    right: 22px;
                    border-width: 6px 6px 0;
                    border-style: solid;
                    border-color: #1f2937 transparent transparent;
                }
                .llm-launcher-wrap:hover .llm-tooltip,
                .llm-launcher-wrap.show-tip .llm-tooltip {
                    opacity: 1;
                    transform: translateY(0);
                }

                /* Animated launcher - attention grabbing shake & bounce */
                .llm-toggle-btn {
                    width: auto;
                    min-width: 60px;
                    height: 56px;
                    padding: 0 20px;
                    border-radius: 28px;
                    background: linear-gradient(135deg, ${this.config.theme.primaryColor} 0%, color-mix(in srgb, ${this.config.theme.primaryColor} 70%, #000) 100%);
                    color: white;
                    border: none;
                    cursor: pointer;
                    font-size: 15px;
                    font-weight: 600;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    letter-spacing: 0.3px;
                    box-shadow: 0 6px 20px rgba(0,0,0,0.25), 0 0 25px ${this.config.theme.primaryColor}50;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    transition: transform 0.18s, box-shadow 0.18s;
                    animation: llm-shake-bounce 1.5s ease-in-out infinite;
                }

                @keyframes llm-shake-bounce {
                    0%, 100% { transform: translateY(0) rotate(0deg); }
                    10% { transform: translateY(-8px) rotate(-3deg); }
                    20% { transform: translateY(-4px) rotate(2deg); }
                    30% { transform: translateY(-10px) rotate(-2deg); }
                    40% { transform: translateY(-5px) rotate(1deg); }
                    50% { transform: translateY(-8px) rotate(0deg); }
                    60% { transform: translateY(-3px) rotate(1deg); }
                    70% { transform: translateY(-6px) rotate(-1deg); }
                    80% { transform: translateY(-2px) rotate(1deg); }
                    90% { transform: translateY(-4px) rotate(0deg); }
                }

                .llm-toggle-btn .llm-btn-icon {
                    line-height: 1;
                    flex-shrink: 0;
                    display: flex;
                    align-items: center;
                    animation: llm-icon-wiggle 0.8s ease-in-out infinite;
                }

                @keyframes llm-icon-wiggle {
                    0%, 100% { transform: rotate(0deg) scale(1); }
                    25% { transform: rotate(-10deg) scale(1.1); }
                    75% { transform: rotate(10deg) scale(1.1); }
                }

                .llm-toggle-btn .llm-btn-label {
                    font-size: 15px;
                    font-weight: 600;
                    white-space: nowrap;
                }

                .llm-toggle-btn:hover {
                    transform: translateY(-3px) scale(1.05);
                    box-shadow: 0 12px 30px rgba(0,0,0,0.3), 0 0 50px ${this.config.theme.primaryColor}80;
                    animation: none;
                }

                .llm-toggle-btn:active {
                    transform: scale(0.97);
                }

                /* Ring ripple effect around button */
                .llm-launcher-wrap::before {
                    content: '';
                    position: absolute;
                    bottom: 0;
                    right: 0;
                    width: 70px;
                    height: 56px;
                    border-radius: 28px;
                    background: transparent;
                    border: 3px solid ${this.config.theme.primaryColor};
                    opacity: 0;
                    animation: llm-ring-pulse 2s ease-out infinite;
                    pointer-events: none;
                }

                @keyframes llm-ring-pulse {
                    0% { transform: scale(1); opacity: 0.6; }
                    100% { transform: scale(1.5); opacity: 0; }
                }

                /* Notification badge */
                .llm-notification-badge {
                    position: absolute;
                    top: -8px;
                    right: -8px;
                    background: #ef4444;
                    color: white;
                    font-size: 11px;
                    font-weight: bold;
                    min-width: 20px;
                    height: 20px;
                    border-radius: 10px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 0 6px;
                    box-shadow: 0 2px 8px rgba(239,68,68,0.5);
                    animation: llm-badge-pulse 1.5s ease-in-out infinite;
                    z-index: 10;
                }

                @keyframes llm-badge-pulse {
                    0%, 100% { transform: scale(1); }
                    50% { transform: scale(1.15); }
                }

                /* Bouncing arrow indicator */
                .llm-bounce-arrow {
                    position: absolute;
                    bottom: 8px;
                    right: 50px;
                    animation: llm-bounce 1.5s ease-in-out infinite;
                    opacity: 0.8;
                }

                @keyframes llm-bounce {
                    0%, 100% { transform: translateY(0); }
                    50% { transform: translateY(-6px); }
                }
            `;

            const styleSheet = document.createElement('style');
            styleSheet.textContent = style;
            document.head.appendChild(styleSheet);

            const widget = document.createElement('div');
            widget.id = 'llm-chatbot-widget';
            widget.style.display = 'none';
            const headerTitle = this.config.tenantConfig?.name || 'AI Assistant';
            widget.innerHTML = `
                <div class="llm-chat-container">
                    <div class="llm-chat-header">
                        <div class="llm-header-left">
                            <div class="llm-header-avatar"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="22" height="22"><defs><linearGradient id="hg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#6366f1"/><stop offset="100%" stop-color="#8b5cf6"/></linearGradient></defs><circle cx="40" cy="8" r="5" fill="url(#hg)"/><rect x="38" y="12" width="4" height="8" rx="2" fill="url(#hg)"/><rect x="8" y="18" width="64" height="48" rx="18" fill="url(#hg)"/><rect x="16" y="25" width="48" height="34" rx="12" fill="#1e1b4b"/><ellipse cx="30" cy="38" rx="6" ry="7" fill="white"/><ellipse cx="50" cy="38" rx="6" ry="7" fill="white"/><circle cx="30" cy="38" r="3" fill="#6366f1"/><circle cx="50" cy="38" r="3" fill="#6366f1"/><path d="M28 52 Q40 62 52 52" stroke="#a5b4fc" stroke-width="3" fill="none" stroke-linecap="round"/></svg></div>
                            <div class="llm-header-info">
                                <div class="llm-header-name">${headerTitle}</div>
                                <div class="llm-header-status"><span class="llm-status-dot"></span>Online — ready to help</div>
                            </div>
                        </div>
                        <button class="llm-close-btn" style="background:none;border:none;color:white;cursor:pointer;font-size:22px;line-height:1;padding:4px;">✕</button>
                    </div>
                    <div class="llm-chat-messages" id="llm-messages"></div>
                    <div id="llm-lead-form" style="display:none;"></div>
                    <div class="llm-chat-input" id="llm-chat-input" style="display:flex;flex-direction:row;align-items:center;gap:8px;padding:10px 12px;border-top:1px solid #e5e7eb;background:#f9fafb;flex-wrap:nowrap;">
                        <input type="text" id="llm-message-input" maxlength="5000" placeholder="Type a message..." style="flex:1 1 0;min-width:0;width:0;border:1.5px solid #d1d5db;border-radius:22px;padding:9px 14px;font-size:14px;outline:none;background:#fff;color:#111827;box-sizing:border-box;">
                        <button id="llm-send-btn" title="Send" style="flex:0 0 40px;width:40px;height:40px;min-width:40px;border-radius:50%;border:none;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;color:white;">&#9658;</button>
                    </div>
                    <div id="llm-char-counter" style="display:none;padding:4px 16px 8px;font-size:11px;color:#6b7280;text-align:right;background:#f9fafb;border-top:1px solid #f3f4f6;"></div>
                </div>
            `;
            document.body.appendChild(widget);

            // Launcher wrapper: tooltip + button
            const launcherWrap = document.createElement('div');
            launcherWrap.className = 'llm-launcher-wrap';
            launcherWrap.id = 'llm-launcher-wrap';

            const tooltip = document.createElement('div');
            tooltip.className = 'llm-tooltip';
            tooltip.textContent = '👋 Hi! Need help? Click to chat!';

            const toggleBtn = document.createElement('button');
            toggleBtn.className = 'llm-toggle-btn';
            toggleBtn.id = 'llm-toggle-btn';
            toggleBtn.style.position = 'relative';
            const robotSVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="32" height="32" style="display:block;flex-shrink:0">
  <defs>
    <linearGradient id="rbg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#6366f1"/>
      <stop offset="100%" stop-color="#8b5cf6"/>
    </linearGradient>
    <linearGradient id="rbg2" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#a5b4fc"/>
      <stop offset="100%" stop-color="#c4b5fd"/>
    </linearGradient>
  </defs>
  <circle cx="40" cy="8" r="5" fill="url(#rbg)"/>
  <rect x="38" y="12" width="4" height="8" rx="2" fill="url(#rbg)"/>
  <rect x="8" y="18" width="64" height="48" rx="18" fill="url(#rbg)"/>
  <circle cx="8" cy="42" r="8" fill="url(#rbg2)"/>
  <circle cx="72" cy="42" r="8" fill="url(#rbg2)"/>
  <rect x="16" y="25" width="48" height="34" rx="12" fill="#1e1b4b"/>
  <ellipse cx="30" cy="38" rx="6" ry="7" fill="white"/>
  <ellipse cx="50" cy="38" rx="6" ry="7" fill="white"/>
  <circle cx="30" cy="38" r="3" fill="#6366f1"/>
  <circle cx="50" cy="38" r="3" fill="#6366f1"/>
  <path d="M28 52 Q40 62 52 52" stroke="url(#rbg2)" stroke-width="3" fill="none" stroke-linecap="round"/>
</svg>`;
            toggleBtn.innerHTML = `<span class="llm-btn-icon" style="display:flex;align-items:center">${robotSVG}</span><span class="llm-btn-label">💬 Chat</span><span class="llm-notification-badge" id="llm-notify-badge" style="display:none;">0</span>`;

            launcherWrap.appendChild(tooltip);
            launcherWrap.appendChild(toggleBtn);
            document.body.appendChild(launcherWrap);
        },

        // Attach event listeners
        attachEventListeners: function() {
            const toggleBtn = document.getElementById('llm-toggle-btn');
            const closeBtn = document.querySelector('.llm-close-btn');
            const sendBtn = document.getElementById('llm-send-btn');

            // Apply brand color to send button (inline style can't use JS template vars)
            if (sendBtn) sendBtn.style.background = this.config.theme.primaryColor || '#3b82f6';
            const messageInput = document.getElementById('llm-message-input');
            const widget = document.getElementById('llm-chatbot-widget');
            const leadForm = document.getElementById('llm-lead-form');
            const leadSubmit = document.getElementById('llm-lead-submit');
            const leadSkip = document.getElementById('llm-lead-skip');
            const chatInput = document.getElementById('llm-chat-input');

            // Debug logging
            console.log('LLMChatbot: Attaching event listeners');
            console.log('  toggleBtn:', toggleBtn ? 'found' : 'NOT FOUND');
            console.log('  closeBtn:', closeBtn ? 'found' : 'NOT FOUND');
            console.log('  sendBtn:', sendBtn ? 'found' : 'NOT FOUND');
            console.log('  messageInput:', messageInput ? 'found' : 'NOT FOUND');
            console.log('  widget:', widget ? 'found' : 'NOT FOUND');

            const launcherWrap = document.getElementById('llm-launcher-wrap');

            if (!toggleBtn || !widget) {
                console.error('LLMChatbot: Required elements not found!');
                return;
            }

            // Auto-show tooltip for 3 s on first load, then hide
            if (launcherWrap) {
                launcherWrap.classList.add('show-tip');
                setTimeout(() => launcherWrap.classList.remove('show-tip'), 3000);
            }

            // Toggle button click handler
            toggleBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                console.log('LLMChatbot: Toggle button clicked');
                
                const isHidden = widget.style.display === 'none' || widget.style.display === '';
                console.log('  isHidden:', isHidden, 'current display:', widget.style.display);
                
                if (isHidden) {
                    // Show widget, hide launcher
                    widget.style.display = 'block';
                    if (launcherWrap) launcherWrap.style.display = 'none';
                    
                    // Clear notification badge
                    LLMChatbot._clearNotificationBadge();
                    
                    // Show welcome message on first open
                    if (LLMChatbot.config.tenantConfig?.welcome_message) {
                        const messagesDiv = document.getElementById('llm-messages');
                        if (messagesDiv && messagesDiv.children.length === 0) {
                            LLMChatbot.addMessageToUI(LLMChatbot.config.tenantConfig.welcome_message, 'assistant');
                        }
                    }
                    
                    // Scroll to bottom and focus input
                    setTimeout(() => {
                        const messagesDiv = document.getElementById('llm-messages');
                        if (messagesDiv) messagesDiv.scrollTop = messagesDiv.scrollHeight;
                        const input = document.getElementById('llm-message-input');
                        if (input) input.focus();
                    }, 50);
                } else {
                    // Hide widget, show launcher
                    widget.style.display = 'none';
                    if (launcherWrap) launcherWrap.style.display = 'flex';
                }
            });

            // Close button handler
            if (closeBtn) {
                closeBtn.addEventListener('click', function() {
                    console.log('LLMChatbot: Close button clicked');
                    widget.style.display = 'none';
                    if (launcherWrap) launcherWrap.style.display = 'flex';
                });
            }

            // Send button and input handler
            if (sendBtn) {
                sendBtn.addEventListener('click', function() {
                    LLMChatbot.sendMessage();
                });
            }

            if (messageInput) {
                messageInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        LLMChatbot.sendMessage();
                    }
                });

                // Character/word counter - shows real-time feedback
                messageInput.addEventListener('input', function() {
                    const content = this.value;
                    const MAX_CHARS = 150;  // ~25 words - plenty for chat
                    const counter = document.getElementById('llm-char-counter');
                    
                    if (!content.trim()) {
                        if (counter) counter.style.display = 'none';
                        return;
                    }

                    const charCount = content.length;
                    const wordCount = content.trim().split(/\s+/).filter(w => w).length;
                    
                    if (counter) {
                        counter.style.display = 'block';
                        
                        // Color coding based on usage
                        if (charCount > MAX_CHARS) {
                            counter.style.color = '#dc2626';
                            counter.textContent = '⚠️ Too long! ' + charCount + ' chars - max ' + MAX_CHARS;
                        } else if (charCount > MAX_CHARS * 0.8) {
                            counter.style.color = '#f59e0b';
                            counter.textContent = '⚠️ ' + charCount + '/' + MAX_CHARS + ' chars';
                        } else {
                            counter.style.color = '#9ca3af';
                            counter.textContent = charCount + ' chars';
                        }
                    }
                });
            }
            
            // Lead form submit handler
            if (leadSubmit) {
                leadSubmit.addEventListener('click', function() {
                    LLMChatbot._submitLeadForm();
                });
            }
            
            // Lead form skip handler
            if (leadSkip) {
                leadSkip.addEventListener('click', function() {
                    LLMChatbot._skipLeadForm();
                });
            }
        },

        // Send message to API
        sendMessage: function() {
            const input = document.getElementById('llm-message-input');
            const content = input.value.trim();
            
            if (!content) return;

            // Character limit check - 150 chars (~25 words) is plenty for chat
            const MAX_CHARS = 150;
            if (content.length > MAX_CHARS) {
                this.addMessageToUI('Your message is too long. Please limit to ' + MAX_CHARS + ' characters.', 'assistant');
                return;
            }

            // Show lead form after 3 free messages (industry standard)
            const msgCount = this._incrementMessageCount();
            const leadCollected = this._isLeadCollected();
            if (msgCount >= 3 && !leadCollected) {
                // Add user message but show lead form instead
                this.addMessageToUI(content, 'user');
                input.value = '';
                this._showLeadForm();
                return;
            }

            // Add user message to UI
            this.addMessageToUI(content, 'user');
            input.value = '';

            // Show typing indicator
            this._showTypingIndicator();

            // Send to API
            const authHeader = this.config.authToken || this.config.apiKey || '';
            
            fetch(`${this.config.apiUrl}/api/chat/message/${this.config.tenantId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(authHeader ? { 'X-API-Key': authHeader } : {})
                },
                body: JSON.stringify({
                    content,
                    session_id: this.config.sessionId || null,
                }),
                signal: AbortSignal.timeout(30000)
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => {
                        throw new Error(err.detail || `HTTP ${response.status}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                this._hideTypingIndicator();
                console.log('API Response:', data);
                if (data && data.session_id) {
                    this.config.sessionId = data.session_id;
                    this._saveSessionId(data.session_id);
                }
                if (data.content) {
                    this.addMessageToUI(data.content, 'assistant', data.id);
                } else {
                    console.error('No content in response:', data);
                    this.addMessageToUI('Sorry, I did not get a response. Please try again.', 'assistant');
                }
            })
            .catch(error => {
                this._hideTypingIndicator();
                console.error('Error sending message:', error);
                let errorMsg = 'Please try again.';
                if (error.name === 'TimeoutError' || error.name === 'AbortError') {
                    errorMsg = 'Request timed out. The server took too long to respond. Please try again.';
                } else if (error.message) {
                    errorMsg = error.message;
                }
                this.addMessageToUI('Error: ' + errorMsg, 'assistant');
            });
        },

        _sessionStorageKey: function() {
            return `llmchat_session_${this.config.tenantId || 'unknown'}`;
        },

        _loadStoredSessionId: function() {
            try {
                return window.localStorage.getItem(this._sessionStorageKey());
            } catch (e) {
                return null;
            }
        },

        _saveSessionId: function(sessionId) {
            if (!sessionId) return;
            try {
                window.localStorage.setItem(this._sessionStorageKey(), sessionId);
            } catch (e) {
                // Ignore storage errors in restricted browser modes.
            }
        },

        // Show lead collection form as inline chat card
        _showLeadForm: function() {
            const messagesDiv = document.getElementById('llm-messages');
            const chatInput = document.getElementById('llm-chat-input');
            const input = document.getElementById('llm-message-input');
            if (!messagesDiv) return;

            // Don't show twice
            if (document.getElementById('llm-inline-lead-form')) return;

            if (chatInput) chatInput.style.display = 'none';
            if (input) input.disabled = true;

            const card = document.createElement('div');
            card.id = 'llm-inline-lead-form';
            card.style.cssText = [
                'background:#f1f5f9',
                'border-radius:10px',
                'padding:10px 12px',
                'margin:4px 0',
                'width:100%',
                'max-width:100%',
                'box-sizing:border-box',
                'font-family:inherit',
            ].join(';');
            const inp = 'display:block;width:100%;border:none;border-bottom:1px solid #cbd5e1;background:transparent;padding:5px 2px;font-size:12px;margin-bottom:6px;box-sizing:border-box;outline:none;color:#1e293b;font-family:inherit;';
            card.innerHTML = `
                <p style="font-size:11px;color:#64748b;margin:0 0 8px;line-height:1.4;font-weight:500;">Quick intro — we'd love to follow up</p>
                <input id="llm-li-name"  type="text"  placeholder="Name"  style="${inp}">
                <input id="llm-li-email" type="email" placeholder="Email" style="${inp}">
                <input id="llm-li-phone" type="tel"   placeholder="Phone" style="${inp}margin-bottom:9px;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <button id="llm-li-submit" style="flex:1;border:none;border-radius:16px;padding:6px 0;font-size:12px;font-weight:600;color:#fff;cursor:pointer;min-height:30px;">Continue ›</button>
                    <span id="llm-li-skip" style="font-size:11px;color:#94a3b8;cursor:pointer;white-space:nowrap;text-decoration:underline;">skip</span>
                </div>
                <div id="llm-li-error" style="color:#ef4444;font-size:11px;margin-top:4px;display:none;"></div>
            `;
            messagesDiv.appendChild(card);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;

            // Apply brand color to submit button
            const submitBtn = document.getElementById('llm-li-submit');
            if (submitBtn) submitBtn.style.background = this.config.theme.primaryColor || '#3b82f6';

            // Focus first field
            setTimeout(() => { const f = document.getElementById('llm-li-name'); if(f) f.focus(); }, 100);

            // Wire up events
            if (submitBtn) submitBtn.addEventListener('click', () => this._submitInlineLeadForm());
            const skipBtn = document.getElementById('llm-li-skip');
            if (skipBtn) skipBtn.addEventListener('click', () => this._skipInlineLeadForm());

            // Allow Enter key to submit
            ['llm-li-name','llm-li-email','llm-li-phone'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') this._submitInlineLeadForm(); });
            });
        },

        _submitInlineLeadForm: function() {
            const name  = (document.getElementById('llm-li-name')  || {}).value?.trim() || '';
            const email = (document.getElementById('llm-li-email') || {}).value?.trim() || '';
            const phone = (document.getElementById('llm-li-phone') || {}).value?.trim() || '';
            const errDiv = document.getElementById('llm-li-error');

            if (!name || !email || !phone) {
                if (errDiv) { errDiv.style.display = 'block'; errDiv.textContent = 'Please fill in all fields.'; }
                return;
            }
            if (errDiv) errDiv.style.display = 'none';

            const submitBtn = document.getElementById('llm-li-submit');
            if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Saving...'; }

            const authHeader = this.config.authToken || this.config.apiKey || '';
            fetch(`${this.config.apiUrl}/api/chat/lead/${this.config.tenantId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...(authHeader ? { 'X-API-Key': authHeader } : {}) },
                body: JSON.stringify({ session_id: this.config.sessionId, name, email, phone })
            })
            .then(r => r.json())
            .then(() => {
                // Remove card, restore input
                const card = document.getElementById('llm-inline-lead-form');
                if (card) card.remove();
                const chatInput = document.getElementById('llm-chat-input');
                const input = document.getElementById('llm-message-input');
                if (chatInput) chatInput.style.display = 'flex';
                if (input) { input.disabled = false; input.focus(); }
                this._saveLeadCollected(true);
                this.addMessageToUI(`Thanks ${name}! How can I help you?`, 'assistant');
            })
            .catch(() => {
                if (errDiv) { errDiv.style.display = 'block'; errDiv.textContent = 'Could not save. Please try again.'; }
                if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Submit & Continue'; }
            });
        },

        _skipInlineLeadForm: function() {
            const card = document.getElementById('llm-inline-lead-form');
            if (card) card.remove();
            const chatInput = document.getElementById('llm-chat-input');
            const input = document.getElementById('llm-message-input');
            if (chatInput) chatInput.style.display = 'flex';
            if (input) { input.disabled = false; input.focus(); }
            this._saveLeadCollected(true);
        },

        // Submit lead form
        _submitLeadForm: function() {
            const name = document.getElementById('llm-lead-name').value.trim();
            const email = document.getElementById('llm-lead-email').value.trim();
            const phone = document.getElementById('llm-lead-phone').value.trim();
            
            if (!name || !email || !phone) {
                alert('Please fill all fields');
                return;
            }
            
            const authHeader = this.config.authToken || this.config.apiKey || '';
            
            // Submit to API
            fetch(`${this.config.apiUrl}/api/chat/lead/${this.config.tenantId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(authHeader ? { 'X-API-Key': authHeader } : {})
                },
                body: JSON.stringify({
                    session_id: this.config.sessionId,
                    name: name,
                    email: email,
                    phone: phone
                })
            })
            .then(r => r.json())
            .then(data => {
                // Hide form, show chat
                const leadForm = document.getElementById('llm-lead-form');
                const chatInput = document.getElementById('llm-chat-input');
                const input = document.getElementById('llm-message-input');
                if (leadForm) leadForm.style.display = 'none';
                if (chatInput) chatInput.style.display = 'flex';
                input.disabled = false;
                input.focus();
                
                // Mark as collected
                this._saveLeadCollected(true);
                
                // Add confirmation message
                this.addMessageToUI(`Thanks ${name}! Your contact info is saved. How can I help you further?`, 'assistant');
            })
            .catch(err => {
                console.error('Lead submit error:', err);
                alert('Error saving info. Please try again.');
            });
        },
        
        // Skip lead form
        _skipLeadForm: function() {
            const leadForm = document.getElementById('llm-lead-form');
            const chatInput = document.getElementById('llm-chat-input');
            const input = document.getElementById('llm-message-input');
            if (leadForm) leadForm.style.display = 'none';
            if (chatInput) chatInput.style.display = 'flex';
            input.disabled = false;
            input.focus();
            
            // Mark as skipped
            this._saveLeadCollected(true);
        },
        
        // Save lead collected state
        _saveLeadCollected: function(collected) {
            try {
                localStorage.setItem(`llm_lead_${this.config.tenantId || 'default'}`, collected ? '1' : '0');
            } catch (e) {}
        },
        
        // Check if lead already collected
        _isLeadCollected: function() {
            try {
                return localStorage.getItem(`llm_lead_${this.config.tenantId || 'default'}`) === '1';
            } catch (e) {
                return false;
            }
        },
        
        // Get message count
        _getMessageCount: function() {
            try {
                return parseInt(localStorage.getItem(`llm_msg_count_${this.config.tenantId || 'default'}`) || 0);
            } catch (e) {
                return 0;
            }
        },
        
        // Increment message count
        _incrementMessageCount: function() {
            try {
                const count = this._getMessageCount() + 1;
                localStorage.setItem(`llm_msg_count_${this.config.tenantId || 'default'}`, count.toString());
                return count;
            } catch (e) {
                return 1;
            }
        },

        // Show typing indicator
        _showTypingIndicator: function() {
            const messagesDiv = document.getElementById('llm-messages');
            if (!messagesDiv) return;
            // Remove existing typing indicator if any
            this._hideTypingIndicator();
            const typingDiv = document.createElement('div');
            typingDiv.id = 'llm-typing-indicator';
            typingDiv.className = 'llm-message assistant';
            typingDiv.innerHTML = '<span class="llm-typing-dots"><span>.</span><span>.</span><span>.</span></span>';
            typingDiv.style.background = '#f3f4f6';
            typingDiv.style.border = '1px solid #e5e7eb';
            typingDiv.style.padding = '12px 16px';
            messagesDiv.appendChild(typingDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        },

        // Hide typing indicator
        _hideTypingIndicator: function() {
            const typingDiv = document.getElementById('llm-typing-indicator');
            if (typingDiv && typingDiv.parentNode) {
                typingDiv.parentNode.removeChild(typingDiv);
            }
        },

        // Add message to UI
        addMessageToUI: function(content, role, messageId = null) {
            const messagesDiv = document.getElementById('llm-messages');
            const msgDiv = document.createElement('div');
            msgDiv.className = `llm-message ${role}`;
            msgDiv.textContent = content;

            if (role === 'assistant' && messageId) {
                const feedbackDiv = document.createElement('div');
                feedbackDiv.className = 'llm-feedback';

                const upBtn = document.createElement('button');
                upBtn.className = 'llm-feedback-btn';
                upBtn.textContent = '👍';

                const downBtn = document.createElement('button');
                downBtn.className = 'llm-feedback-btn';
                downBtn.textContent = '👎';

                upBtn.addEventListener('click', () => {
                    this.submitFeedback(messageId, 1, upBtn, downBtn);
                });

                downBtn.addEventListener('click', () => {
                    this.submitFeedback(messageId, -1, downBtn, upBtn);
                });

                feedbackDiv.appendChild(upBtn);
                feedbackDiv.appendChild(downBtn);
                msgDiv.appendChild(feedbackDiv);
            }

            messagesDiv.appendChild(msgDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;

            // Show notification badge if widget is closed and it's an assistant message
            if (role === 'assistant') {
                const widget = document.getElementById('llm-chatbot-widget');
                const launcherWrap = document.getElementById('llm-launcher-wrap');
                const badge = document.getElementById('llm-notify-badge');
                if (widget && widget.style.display === 'none' && badge && launcherWrap && launcherWrap.style.display !== 'none') {
                    // Show badge with count
                    const currentCount = parseInt(badge.textContent) || 0;
                    badge.textContent = currentCount + 1;
                    badge.style.display = 'flex';
                }
            }
        },

        // Clear notification badge when user opens widget
        _clearNotificationBadge: function() {
            const badge = document.getElementById('llm-notify-badge');
            if (badge) {
                badge.style.display = 'none';
                badge.textContent = '0';
            }
        },

        submitFeedback: function(messageId, score, activeBtn, inactiveBtn) {
            fetch(`${this.config.apiUrl}/api/chat/feedback/${messageId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': this.config.authToken || this.config.apiKey || ''
                },
                body: JSON.stringify({ score })
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to save feedback');
                }
                activeBtn.classList.add('active');
                inactiveBtn.classList.remove('active');
            })
            .catch(error => {
                console.error('Error submitting feedback:', error);
            });
        }
    };

    // Expose globally
    window.LLMChatbot = LLMChatbot;
})();
