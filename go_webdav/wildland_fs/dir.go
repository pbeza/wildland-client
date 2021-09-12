package wildland_fs

import ("errors";  "io/fs"; "time"; "os"; "log"
	"io"
)

type wildland_dir struct {
	fs_object
}



func (dir wildland_dir)Readdir(count int)([]fs.FileInfo, error) {
	// For now just return an empty slice and indicate
	// end of listing
	log.Println("called readdir for ", dir.name)
	if objs, err := dir.fs.Readdir(dir.name); err != nil {
		return nil, err
	} else {
		var err error
		out := make([]fs.FileInfo, 0, len(objs))
		if len(objs) == 0 {
			err = io.EOF
		} else {
			for _, obj := range objs {
				out = append(out, obj)
			}
		}

		
		return out, err
	}
}

func (dir wildland_dir)Read(b []byte) (int, error) {
	return -1, errors.New("read makes no sense for directories")
}

func (dir wildland_dir)Seek(offset int64, whence int) (int64, error) {
	return -1, errors.New("seek makes no sense for directories")
}


func (dir wildland_dir)Close() error {
	return nil
}

func (dir wildland_dir)Stat() (fs.FileInfo, error) {
	log.Println("stat called for: ", dir.Name())
	return dir, nil
}

func (dir wildland_dir)Write(b []byte) (int, error) {
	return 0, errors.New("unimplemented")
}

func (dir wildland_dir)IsDir() bool {
	return true
}

func (dir wildland_dir)Size() int64 {
	return 0
}

func (dir wildland_dir)Mode() fs.FileMode {
	return 0555 | os.ModeDir
}

func (dir wildland_dir)ModTime() time.Time {
	return time.Now()
}

func (dir wildland_dir)Sys() interface {} {
	return nil
}
