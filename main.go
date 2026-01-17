package main

import (
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"antigravity-bridge/automation"
	"antigravity-bridge/mcp"

	"github.com/joho/godotenv"
	tb "gopkg.in/tucnak/telebot.v2"
)

// MsgBuffer aggregates messages for a specific chat
type MsgBuffer struct {
	Timer    *time.Timer
	Messages []*tb.Message
}

var (
	bufferMap  = make(map[int64]*MsgBuffer) // Send by ChatID
	bufferLock sync.Mutex
)

func main() {
	// IMPORTANT: All logs must go to Stderr because Stdout is MCP
	f, err := os.OpenFile("/tmp/gravity_main_debug.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err == nil {
		log.SetOutput(f)
	} else {
		log.SetOutput(os.Stderr)
	}

	// Load .env
	err = godotenv.Load()
	if err != nil {
		log.Println("Warning: Error loading .env file, relying on environment variables")
	}

	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	if token == "" {
		log.Fatal("TELEGRAM_BOT_TOKEN not set")
	}

	b, err := tb.NewBot(tb.Settings{
		Token:  token,
		Poller: &tb.LongPoller{Timeout: 10 * time.Second},
	})
	if err != nil {
		log.Fatal(err)
	}

	// Setup MCP Server
	sendToTg := func(chatIDStr, text string) error {
		cid, err := strconv.ParseInt(chatIDStr, 10, 64)
		if err != nil {
			return err
		}
		chat := &tb.Chat{ID: cid}
		safeText := strings.ReplaceAll(text, "\\n", "\n")
		_, err = b.Send(chat, safeText)
		return err
	}

	mcpServer := mcp.NewServer(sendToTg)

	// Get executable directory
	ex, err := os.Executable()
	if err != nil {
		log.Fatal(err)
	}
	binDir := filepath.Dir(ex)
	templatesDir := filepath.Join(binDir, "templates")

	log.Printf("Started. Binary: %s, TemplatesDir: %s, DISPLAY: %s", ex, templatesDir, os.Getenv("DISPLAY"))

	// Unified Message Handler (Buffers EVERYTHING by ChatID)
	handleMessage := func(m *tb.Message) {
		bufferLock.Lock()
		defer bufferLock.Unlock()

		chatID := m.Chat.ID
		buf, exists := bufferMap[chatID]
		if !exists {
			buf = &MsgBuffer{
				Messages: []*tb.Message{},
			}
			bufferMap[chatID] = buf
		}

		// Append message
		buf.Messages = append(buf.Messages, m)
		log.Printf("Buffered message from %d. Total: %d", chatID, len(buf.Messages))

		// Reset/Start Timer
		if buf.Timer != nil {
			buf.Timer.Stop()
		}

		// Wait 2 seconds quiescence
		buf.Timer = time.AfterFunc(2*time.Second, func() {
			bufferLock.Lock()
			messages := buf.Messages
			delete(bufferMap, chatID)
			bufferLock.Unlock()

			log.Printf("Processing Batch for Chat %d with %d messages", chatID, len(messages))
			if len(messages) == 0 {
				return
			}

			// Sort by time? Usually appended in order of receipt.
			// Telebot doesn't guarantee generic message order perfectly but receipt order is usually fine.
			// Just in case, sort by ID (which is incremental in Telegram)
			sort.Slice(messages, func(i, j int) bool {
				return messages[i].ID < messages[j].ID
			})

			// Collect Content
			var imagePaths []string
			var txtParts []string

			for i, msg := range messages {
				// Text
				if msg.Text != "" {
					txtParts = append(txtParts, msg.Text)
				} else if msg.Caption != "" {
					txtParts = append(txtParts, msg.Caption)
				}

				// Media
				var fID string
				var fExt string = ".png"

				if msg.Photo != nil {
					fID = msg.Photo.FileID
				} else if msg.Document != nil {
					fID = msg.Document.FileID
					if filepath.Ext(msg.Document.FileName) != "" {
						fExt = filepath.Ext(msg.Document.FileName)
					}
					// Check Prefix if needed (skipped for now to be generous)
				}

				if fID != "" {
					// Download
					file := &tb.File{FileID: fID}
					localPath := filepath.Join(os.TempDir(), fmt.Sprintf("tg_batch_%d_%d%s", chatID, i, fExt))
					if err := b.Download(file, localPath); err == nil {
						imagePaths = append(imagePaths, localPath)
					} else {
						log.Printf("Error downloading item: %v", err)
					}
				}
			}

			fullText := strings.Join(txtParts, "\n")
			contentWithContext := "From Telegram [" + strconv.FormatInt(messages[0].Chat.ID, 10) + "]: " + fullText
			if len(imagePaths) > 0 {
				contentWithContext += " (Group/Attachments)"
			}

			go func() {
				defer func() {
					for _, p := range imagePaths {
						os.Remove(p)
					}
				}()

				if len(imagePaths) > 0 {
					automation.FullWorkflowMediaGroup(imagePaths, contentWithContext, templatesDir, func(status string) {
						b.Send(messages[0].Sender, status)
					})
				} else {
					// Text Only
					automation.FullWorkflow(contentWithContext, templatesDir, func(status string) {
						b.Send(messages[0].Sender, status)
					})
				}
			}()
		})
	}

	// Register Handlers
	b.Handle(tb.OnText, handleMessage)
	b.Handle(tb.OnPhoto, handleMessage)
	b.Handle(tb.OnDocument, handleMessage)

	log.Println("Antigravity Bridge Bot & MCP Server Starting...")

	go b.Start()
	go mcpServer.Start()
	select {}
}
