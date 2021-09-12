package wildland_fs

import (
	"fmt"; "log"; "errors"; "context"; "os"; "io/fs"; "time";
	"syscall"
	"golang.org/x/net/webdav"
	"sync"
)


type i_fs_object interface {
	os.FileInfo
	webdav.File

	SetFS(*wildland_fs)
}

type wildland_fs struct {
	pmap map[string]i_fs_object
	wl *wildland
}

type wildland_file struct {
	name string
}


func (fs *wildland_fs)init() {
	fmt.Println("initializing")
	fs.pmap = make(map[string]i_fs_object)

	root_dir := new(wildland_dir)
	root_dir.name = "/"
	root_dir.SetFS(fs)
	
	fs.pmap["/"] = root_dir
	wlref,err := initWildland()
	if(err != nil) {
		log.Fatal(err)
	} else {
		fs.wl = wlref
		wlref.fs = fs
	}
}

func (fs *wildland_fs)Start(wg *sync.WaitGroup) {
	defer func() {
		err := recover()
		log.Println(err)
	}()
	log.Println("starting wildland")
	if err := fs.wl.start(); err != nil {
		log.Fatal("wildland failed to start", err)
	}
	log.Println("wl start() exit")
//	wg.Done()
}


func WildlandFS() *wildland_fs {
	rv := new(wildland_fs)
	rv.init()
	return rv
}

func (fs *wildland_fs)Bless(object *fs_object) {
	object.SetFS(fs)
}

func (fs *wildland_fs)Readdir(path string)([]i_fs_object, error) {
	log.Println("wildand readdir called for path: ", path, fs.wl)
	return fs.wl.readdir(path)
}


// Compliance with FileSystem interface, as stated here:
// https://github.com/golang/net/blob/e898025ed96aa6d08e98132b8dca210e9e7a0cd2/webdav/file.go#L40
func (fs *wildland_fs)Mkdir(ctx context.Context, name string, 
	perm os.FileMode) error {
	log.Println("Mkdir", name)
	return errors.New("i am not implemented")
}

func (fs *wildland_fs)OpenFile(ctx context.Context, name string,
	flag int, perm os.FileMode) (webdav.File, error) {
	log.Println("Open", name)
	if obj, ok := fs.pmap[name]; ok {
		return obj, nil
	} else {
		return nil, syscall.ENOENT
	}
}

func (fs *wildland_fs)RemoveAll(ctx context.Context, name string) error {
	log.Println("RemoveAll", name)
	return errors.New("nonono")
}

func (fs *wildland_fs)Rename(ctx context.Context, old, new string) error {
	log.Println("Rename", old)
	return errors.New("i am not here")
}

func (fs *wildland_fs)Stat(ctx context.Context, name string) (os.FileInfo, error) {
	log.Println("Stat", name)
	if obj, ok := fs.pmap[name]; ok {
		return obj, nil
	} else {
		return nil, syscall.ENOENT
	}
}


func (f wildland_file) Name() string {
	return f.name
}

func (d wildland_dir) Name() string {
	return d.name
}

func (f wildland_file) IsDir() bool {
	return false
}

func (f wildland_file) Size() int64 {
	return 0
}

func (f wildland_file) Mode() fs.FileMode {
	return 0555 | os.ModeDir
}

func (f wildland_file) ModTime() time.Time {
	return time.Now()
}

func (f wildland_file) Sys() interface{} {
	return nil
}
