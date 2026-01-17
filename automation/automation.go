package automation

import (
	"fmt"
	"image"
	// "image/draw"
	_ "image/png"
	"log"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// SetClipboard sets content to X11 clipboard
func SetClipboard(text string) error {
	cmd := exec.Command("xclip", "-selection", "clipboard")
	cmd.Stdin = strings.NewReader(text)
	return cmd.Run()
}

// SetClipboardImage sets an image file to X11 clipboard
func SetClipboardImage(imagePath string) error {
	// xclip -selection clipboard -t image/png -i image.png
	cmd := exec.Command("xclip", "-selection", "clipboard", "-t", "image/png", "-i", imagePath)
	return cmd.Run()
}

// FindAndClick looks for an image on screen and clicks it
// Returns (success bool, logMsg string)
func FindAndClick(imageName string) (bool, string) {
	// Debug Info
	cwd, _ := os.Getwd()
	display := os.Getenv("DISPLAY")
	debugMsg := fmt.Sprintf("CWD: %s, DISPLAY: %s. ", cwd, display)

	// 1. Take screenshot
	screenshotPath := "screen.png"
	os.Remove(screenshotPath)

	out, err := exec.Command("scrot", screenshotPath).CombinedOutput()
	if err != nil {
		errMsg := fmt.Sprintf("Scrot failed: %v, Out: %s", err, string(out))
		log.Println(errMsg)
		return false, debugMsg + errMsg
	}
	defer os.Remove(screenshotPath)

	// 2. Load images
	screenImg, err := loadImage(screenshotPath)
	if err != nil {
		errMsg := fmt.Sprintf("Load Screen failed: %v", err)
		log.Println(errMsg)
		return false, debugMsg + errMsg
	}
	
	tmplImg, err := loadImage(imageName)
	if err != nil {
		errMsg := fmt.Sprintf("Load Tmpl '%s' failed: %v", imageName, err)
		log.Println(errMsg)
		return false, debugMsg + errMsg
	}

	// 3. Find template
	sBounds := screenImg.Bounds()
	debugMsg += fmt.Sprintf("Screen: %dx%d. ", sBounds.Dx(), sBounds.Dy())
	
	x, y, found := findImageInImage(screenImg, tmplImg)
	if found {
		// 4. Click
		clickX := x + 10
		clickY := y + 10
		
		log.Printf("Found %s at %d,%d. Clicking...", imageName, clickX, clickY)
		
		exec.Command("xdotool", "mousemove", fmt.Sprintf("%d", clickX), fmt.Sprintf("%d", clickY)).Run()
		time.Sleep(100 * time.Millisecond)
		exec.Command("xdotool", "click", "1").Run()
		return true, "Success"
	}

	return false, debugMsg + "Image Match Failed."
}

// PasteAndSubmit performs Ctrl+V then Enter
func PasteAndSubmit() {
	log.Println("PasteAndSubmit: Sending Ctrl+V...")
	exec.Command("xdotool", "key", "ctrl+v").Run()
	time.Sleep(200 * time.Millisecond)
	log.Println("PasteAndSubmit: Sending Enter...")
	exec.Command("xdotool", "key", "Return").Run()
}

// MonitorProcess handles the loop
func MonitorProcess(replyingImg, acceptImg string, onThinking func()) {
	log.Println("MonitorProcess: Starting loop...")
	
	// Phase 1: Wait for Replying to appear (Max 10s)
	log.Println("MonitorProcess: Waiting for 'Replying' to appear...")
	waitTicker := time.NewTicker(500 * time.Millisecond)
	waitTimeout := time.After(10 * time.Second)
	appeared := false
	
	WaitForLoop:
	for {
		select {
		case <-waitTimeout:
			log.Println("MonitorProcess: 'Replying' never appeared. Assuming finished or missed.")
			waitTicker.Stop()
			return
		case <-waitTicker.C:
			replyTmpl, err := loadImage(replyingImg)
			if err != nil {
				log.Printf("Error loading answering tmpl: %v", err)
				waitTicker.Stop()
				return 
			}
			
			// Take quick screenshot
			exec.Command("scrot", "monitor_check.png").Run()
			screenImg, err := loadImage("monitor_check.png")
			if err != nil {
				os.Remove("monitor_check.png") // Ensure cleanup even on error
				continue
			}
			os.Remove("monitor_check.png")
			
			_, _, found := findImageInImage(screenImg, replyTmpl)
			if found {
				log.Println("MonitorProcess: 'Replying' detected! Entering monitor loop.")
				appeared = true
				waitTicker.Stop()
				break WaitForLoop
			}
		}
	}

	if !appeared {
		return
	}

	// Phase 2: Monitor Loop
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	timeout := time.After(300 * time.Second) // Safety timeout increased
	lastThinkingTime := time.Time{}
	
	// Retry counter for "Replying" not found (to avoid exiting on flicker)
	notFoundCount := 0
	const maxNotFound = 5 // Increased tolerance

	for {
		select {
		case <-timeout:
			log.Println("MonitorProcess: Safety timeout reached.")
			return
		case <-ticker.C:
			// 1. Take Screenshot
			screenshotPath := "monitor_screen.png"
			os.Remove(screenshotPath)
			exec.Command("scrot", screenshotPath).Run()
			
			screenImg, err := loadImage(screenshotPath)
			if err != nil {
				log.Printf("Error loading screen: %v", err)
				os.Remove(screenshotPath)
				continue
			}
			os.Remove(screenshotPath)
			
			// 2. Check Replying (The Condition)
			replyTmpl, err := loadImage(replyingImg)
			if err != nil {
				log.Printf("Error loading answering tmpl: %v", err)
				return 
			}
			
			_, _, replyingFound := findImageInImage(screenImg, replyTmpl)
			
			if !replyingFound {
				notFoundCount++
				log.Printf("MonitorProcess: 'Replying' not found (%d/%d)", notFoundCount, maxNotFound)
				if notFoundCount >= maxNotFound {
					log.Println("MonitorProcess: 'Replying' gone. Stopping loop.")
					return
				}
				continue
			}
			
			// Reset counter as we found it
			notFoundCount = 0
			
			// 3. Logic A: Send Thinking every 5s
			if time.Since(lastThinkingTime) >= 5*time.Second {
				if onThinking != nil {
					log.Println("MonitorProcess: Sending 'Thinking...'")
					onThinking()
				}
				lastThinkingTime = time.Now()
			}
			
			// 4. Logic B: Click Accept Button
			acceptTmpl, err := loadImage(acceptImg)
			if err == nil {
				x, y, found := findImageInImage(screenImg, acceptTmpl)
				if found {
					log.Println("MonitorProcess: Found Accept button. Clicking...")
					exec.Command("xdotool", "mousemove", strconv.Itoa(x), strconv.Itoa(y), "click", "1").Run()
					// We do NOT return here, we continue monitoring until Replying disappears
				}
			}
		}
	}
}

// checkAndAct is removed/merged into MonitorProcess for clearer flow control

func FullWorkflow(text string, templatesDir string, sendStatus func(string)) {
	// 1. Copy to Clipboard
	if err := SetClipboard(text); err != nil {
		log.Printf("Error setting clipboard: %v", err)
		return // Assuming critical
	}

	// 2. Find Input Box
	inputBoxImg := fmt.Sprintf("%s/input_box.png", templatesDir)
	success, debugLog := FindAndClick(inputBoxImg)
	if success {
		// 3. Paste and Submit
		time.Sleep(500 * time.Millisecond) 
		PasteAndSubmit()
		
		// 4. Monitor
		replyingImg := fmt.Sprintf("%s/Replying.png", templatesDir)
		acceptImg := fmt.Sprintf("%s/accept_button.png", templatesDir)
		MonitorProcess(replyingImg, acceptImg, func() {
			sendStatus("Thinking...")
		})
	} else {
		log.Println("Could not find input_box.png")
		sendStatus("Error [v2]: input_box.png not found. Info: " + debugLog)
	}
}

func FullWorkflowImage(imagePath, templatesDir string, sendStatus func(string)) {
	// 1. Copy Image to Clipboard
	if err := SetClipboardImage(imagePath); err != nil {
		log.Printf("Error setting clipboard image: %v", err)
		sendStatus("Error setting clipboard image: " + err.Error())
		return
	}

	// 2. Find Input Box
	inputBoxImg := fmt.Sprintf("%s/input_box.png", templatesDir)
	success, debugLog := FindAndClick(inputBoxImg)
	if success {
		// 3. Paste
		PasteAndSubmit()
		
		// 4. Monitor Process
		replyingImg := fmt.Sprintf("%s/Replying.png", templatesDir)
		acceptImg := fmt.Sprintf("%s/accept_button.png", templatesDir)
		
		MonitorProcess(replyingImg, acceptImg, func() {
			sendStatus("Thinking...")
		})
	} else {
		log.Println("Could not find input_box.png")
		sendStatus("Error [v2]: input_box.png (img flow) not found. Info: " + debugLog)
	}
}

func FullWorkflowMediaGroup(imagePaths []string, text string, templatesDir string, sendStatus func(string)) {
	// 1. Find Input Box
	inputBoxImg := fmt.Sprintf("%s/input_box.png", templatesDir)
	success, debugLog := FindAndClick(inputBoxImg)
	if !success {
		log.Println("Could not find input_box.png")
		sendStatus("Error [v2]: input_box.png (media group) not found. Info: " + debugLog)
		return
	}

	// 2. Process Images
	for i, imgPath := range imagePaths {
		log.Printf("Processing image %d/%d: %s", i+1, len(imagePaths), imgPath)
		if err := SetClipboardImage(imgPath); err != nil {
			log.Printf("Error setting clipboard image %s: %v", imgPath, err)
			sendStatus(fmt.Sprintf("Error setting clipboard image %d: %v", i+1, err))
			continue
		}
		
		// Paste
		time.Sleep(500 * time.Millisecond) // Wait for clipboard to set
		log.Println("Pasting image...")
		exec.Command("xdotool", "key", "ctrl+v").Run()
		time.Sleep(500 * time.Millisecond) // Wait for paste to render
	}

	// 3. Process Text
	if text != "" {
		log.Printf("Processing text caption")
		if err := SetClipboard(text); err != nil {
			log.Printf("Error setting clipboard text: %v", err)
			sendStatus("Error setting clipboard text: " + err.Error())
		} else {
			time.Sleep(300 * time.Millisecond)
			log.Println("Pasting text...")
			exec.Command("xdotool", "key", "ctrl+v").Run()
			time.Sleep(300 * time.Millisecond)
		}
	}

	// 4. Submit
	log.Println("Waiting for uploads to stabilize...")
	time.Sleep(2 * time.Second) // Wait for images to be fully processed by IDE
	log.Println("Sending Enter...")
	exec.Command("xdotool", "key", "Return").Run()

	// 5. Monitor
	replyingImg := fmt.Sprintf("%s/Replying.png", templatesDir)
	acceptImg := fmt.Sprintf("%s/accept_button.png", templatesDir)
	
	MonitorProcess(replyingImg, acceptImg, func() {
		sendStatus("Thinking...")
	})
}

// --- Image Processing Helpers ---

func loadImage(path string) (image.Image, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	img, _, err := image.Decode(f)
	return img, err
}

func abs(x int64) int64 {
	if x < 0 { return -x }
	return x
}

func colorDiff(r1, g1, b1, a1, r2, g2, b2, a2 uint32) bool {
    // Tolerance: e.g. 5000 out of 65535 per channel (~7%)
    const tol = 8000 
    if abs(int64(r1)-int64(r2)) > tol { return false }
    if abs(int64(g1)-int64(g2)) > tol { return false }
    if abs(int64(b1)-int64(b2)) > tol { return false }
    // Ignore alpha? or check it.
    // Screens usually full opacity.
    return true
}

// Fast image search using raw buffers
func findImageInImage(screen, template image.Image) (int, int, bool) {
	bounds := screen.Bounds()
	tmpBounds := template.Bounds()
	
	// Helper to get raw data if possible
	type rawImage interface {
		PixOffset(x, y int) int
		Pix() []uint8
	}

	// Try to cast to supported types for direct access
	var sPix, tPix []uint8
	var sStride, tStride int
	var sOk, tOk bool

	// Handle Screen
	switch s := screen.(type) {
	case *image.NRGBA:
		sPix = s.Pix
		sStride = s.Stride
		sOk = true
	case *image.RGBA:
		sPix = s.Pix
		sStride = s.Stride
		sOk = true
	}

	// Handle Template
	switch t := template.(type) {
	case *image.NRGBA:
		tPix = t.Pix
		tStride = t.Stride
		tOk = true
	case *image.RGBA:
		tPix = t.Pix
		tStride = t.Stride
		tOk = true
	}

	// Optimized path
	if sOk && tOk {
		return findImageInImageFast(sPix, sStride, bounds, tPix, tStride, tmpBounds)
	}

	log.Println("Warning: Slow path used for image search (unsupported image type)")

	// Fallback to slow path
	r0, g0, b0, a0 := template.At(tmpBounds.Min.X, tmpBounds.Min.Y).RGBA()
	isMatch := func(c1r, c1g, c1b, c1a uint32) bool {
		return colorDiff(c1r, c1g, c1b, c1a, r0, g0, b0, a0)
	}

	for y := bounds.Min.Y; y < bounds.Max.Y-tmpBounds.Dy(); y++ {
		for x := bounds.Min.X; x < bounds.Max.X-tmpBounds.Dx(); x++ {
			r, g, b, a := screen.At(x, y).RGBA()
			if !isMatch(r, g, b, a) {
				continue
			}
			if slowMatchAt(screen, template, x, y) {
				return x, y, true
			}
		}
	}
	return -1, -1, false
}

func findImageInImageFast(sPix []uint8, sStride int, sBounds image.Rectangle, tPix []uint8, tStride int, tBounds image.Rectangle) (int, int, bool) {
	w, h := tBounds.Dx(), tBounds.Dy()
	
	// Pre-read template first pixel (assuming 0,0 in template relative coords)
	// Template is usually small, so tPix[0] is (Min.X, Min.Y) if offset is handled or if we just assume 0-indexed buffer?
	// image.Image buffer usually starts at 0 index for the Rect.Min? NO.
	// We must use PixOffset.
	
	// ACTUALLY: The Pix slice covers the Rect.
	// But let's assume valid images.
	
	// Let's just use the relative offsets.
	
	maxY := sBounds.Max.Y - h
	maxX := sBounds.Max.X - w
	
	// Safe checks
	if maxY < sBounds.Min.Y || maxX < sBounds.Min.X { return -1, -1, false }

	// Template first pixel
	// Note: NRGBA/RGBA Pix arrays usually start at 0 for the top-left of the Rect?
	// It depends on subimage. But here we loaded from file, so it's likely origin 0,0.
	// Safe way for template (which we loaded):
	tr0, tg0, tb0, _ := tPix[0], tPix[1], tPix[2], tPix[3]

	// Screen scanning
	// The screen might be a subimage? scrot usually returns full image. sBounds.Min is 0,0.
	
	for y := sBounds.Min.Y; y < maxY; y++ {
		sRowOffset := (y - sBounds.Min.Y) * sStride
		for x := sBounds.Min.X; x < maxX; x++ {
			sOff := sRowOffset + (x - sBounds.Min.X)*4
			
			// Fast check first pixel
			// We compare raw bytes. colorDiff logic was: abs(r1-r2) > tol (8000 on 16-bit scale).
			// 8000/65535 ~ 12%. 
			// On 8-bit scale: 255 * 0.12 ~ 30.
			
			if !bytesSimilar(sPix[sOff], tr0) ||
			   !bytesSimilar(sPix[sOff+1], tg0) ||
			   !bytesSimilar(sPix[sOff+2], tb0) {
				continue
			}

			if fastMatchRaw(sPix, sStride, x, y, sBounds.Min.X, sBounds.Min.Y, tPix, tStride, w, h) {
				return x, y, true
			}
		}
	}
	return -1, -1, false
}

func bytesSimilar(a, b uint8) bool {
	diff := int(a) - int(b)
	if diff < 0 { diff = -diff }
	return diff < 30 // Approx tolerance similar to original
}

// Compare full template
func fastMatchRaw(sPix []uint8, sStride int, sx, sy, sMinX, sMinY int, tPix []uint8, tStride int, w, h int) bool {
	// Center check first?
	cx, cy := w/2, h/2
	sOffC := (sy + cy - sMinY)*sStride + (sx + cx - sMinX)*4
	tOffC := cy*tStride + cx*4
	
	if !bytesSimilar(sPix[sOffC], tPix[tOffC]) ||
	   !bytesSimilar(sPix[sOffC+1], tPix[tOffC+1]) ||
	   !bytesSimilar(sPix[sOffC+2], tPix[tOffC+2]) {
		return false
	}

	// Full check
	for y := 0; y < h; y++ {
		sRow := (sy + y - sMinY) * sStride
		tRow := y * tStride
		for x := 0; x < w; x++ {
			sOff := sRow + (sx + x - sMinX)*4
			tOff := tRow + x*4
			
			if !bytesSimilar(sPix[sOff], tPix[tOff]) ||
			   !bytesSimilar(sPix[sOff+1], tPix[tOff+1]) ||
			   !bytesSimilar(sPix[sOff+2], tPix[tOff+2]) {
				return false
			}
		}
	}
	return true
}

func slowMatchAt(screen, template image.Image, sx, sy int) bool {
	tBounds := template.Bounds()
	w, h := tBounds.Dx(), tBounds.Dy()
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			r1, g1, b1, a1 := screen.At(sx+x, sy+y).RGBA()
			r2, g2, b2, a2 := template.At(tBounds.Min.X+x, tBounds.Min.Y+y).RGBA()
			if !colorDiff(r1, g1, b1, a1, r2, g2, b2, a2) {
				return false
			}
		}
	}
	return true
}
