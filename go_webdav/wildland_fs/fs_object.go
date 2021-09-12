package wildland_fs

import (
	"io/fs"
	"time"
)

type fs_object struct {
	fs.FileInfo
	i_fs_object
	fs *wildland_fs
	name string
}

// Blessable implementation
func (o *fs_object)SetFS(fs *wildland_fs) {
	o.fs = fs
}

// Webdav.File implementation
func (o *fs_object)Close() error {
	panic("Abstract method")
}


func (o *fs_object)Read(p []byte) (int, error) {
	panic("Abstract method")
}

func (o *fs_object)Readdir(count int) ([]fs.FileInfo, error) {
	panic("Abstract method")
}

// fs.File implementation
func (o *fs_object)Name() string {
	return o.name
}

func (o *fs_object)Size() int64 {
	return 0
}

func (o *fs_object)Mode() fs.FileMode {
	return 0777
}

func (o *fs_object)ModTime() time.Time {
	return time.Now()
}

func (o *fs_object)IsDir() bool {
	return true
}

func (o *fs_object)Sys() interface{} {
	return nil
}
