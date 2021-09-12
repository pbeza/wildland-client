package main

//import "fmt"
import ("os"; "os/signal"; "syscall")
import "log"
import "golang.org/x/net/webdav"
import "net/http"
import "wildland.io/webdav_frontend/wildland_fs"
import "sync"


// Temporarily hardcoded
var socketPath = "/tmp/wlfuse.sock"

func main() {
	setupTerminationHandler()
	fs := wildland_fs.WildlandFS()
	wg := new(sync.WaitGroup)
	wg.Add(1)
	server := &webdav.Handler {
		  FileSystem: fs,
			LockSystem: webdav.NewMemLS(),
		}


	http.HandleFunc("/", func(w http.ResponseWriter,
		req *http.Request) {
		if  req.Method == "GET" {
			log.Println("SHOULD NOT HAPPEN! listing for: ", 
				req.URL.Path) 
			return
		}
		server.ServeHTTP(w, req)
	})
	
	http_fn := func() {
		log.Println("webdav server begin to listen")
		log.Println(http.ListenAndServe(":8080", nil))
		log.Println("webdav server terminated")
		wg.Done()
	}
	go  http_fn()
	go fs.Start(wg)
	wg.Wait()
	log.Println("wait group does not wait anymore")
}


func setupTerminationHandler() {
	c := make(chan os.Signal)
	signal.Notify(c, os.Interrupt, syscall.SIGTERM)
	go func() {
		<- c
		os.Remove(socketPath)
		os.Exit(0)
	}()
}
