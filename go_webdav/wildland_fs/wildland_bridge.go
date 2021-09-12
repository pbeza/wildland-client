package wildland_fs

// #cgo pkg-config: python3-embed
// #include <Python.h>
//
// // C macros need to be wrapped in C functions to be exposed to GO! God bless you, Google!
// void decref(PyObject *o) { Py_DECREF(o); }
// void incref(PyObject *o) { Py_INCREF(o); }
// void tuple_set_item(PyObject *t, int i, PyObject *v) { PyTuple_SET_ITEM(t,i,v); }
import "C"
import "unsafe"
import "errors"
import "log"
import "os"
import "golang.org/x/text/encoding/unicode/utf32"

/*
This is the bridge to Python code. No Python awareness allowed
in other files.
*/

type PyObjRef *C.struct__object


type wildland struct {
	imports map[string]PyObjRef
	save *C.PyThreadState
	fspy PyObjRef
	fs *wildland_fs
}

func newPyObject(module PyObjRef, class string, args... PyObjRef) PyObjRef {
	cClass := C.CString(class)
	defer C.free(unsafe.Pointer(cClass))

	pyname := C.PyUnicode_FromString(cClass)
	defer C.decref(pyname)

	moduleDict := C.PyModule_GetDict(module)
	classObj := C.PyDict_GetItem(moduleDict, pyname)
	tupleArgs := C.PyTuple_New(C.long(len(args)))
	for i, arg := range args {
		C.tuple_set_item(tupleArgs, C.int(i), arg)
	}

	defer C.decref(tupleArgs)
	log.Println("class for ", class, " is ", classObj)
	inst := C.PyObject_Call(classObj, tupleArgs, nil)

	return inst
}

func callPyMethod(pyfs PyObjRef, methodName string, args ...PyObjRef) (PyObjRef,error) {
	cMethodName := C.CString(methodName)
	defer C.free(unsafe.Pointer(cMethodName))
	
	method := C.PyObject_GetAttrString(pyfs, cMethodName)
	targs := C.PyTuple_New(C.long(len(args)))
	for i,v := range args {
		C.tuple_set_item(targs, C.int(i), v)
	}
	defer C.decref(targs)
	dargs := C.PyDict_New()
	defer C.decref(dargs)
	res := C.PyObject_Call(method, targs, dargs)
	return res, nil // no error handling for now ;(
}

func (wl *wildland)importModule(name string) (PyObjRef,error) {
	if mod,ok := wl.imports[name]; ok {
		return mod, nil
	} else {
		cname := C.CString(name)
		defer C.free(unsafe.Pointer(cname))
		log.Println("going to import Python module ", name)
		modref := C.PyImport_ImportModule(cname)
		if(modref != nil) {
			return modref, nil
		} else {
			return nil, errors.New("unable to import module")
		}
	}
}

func initWildland() (*wildland, error) {
	wl := new(wildland)
	err := wl.setupEnvironment()
	return wl, err
}

func (wl *wildland)setupEnvironment() error {
	/* Could insert venv site packages into PYTHONPATH maybe (needed for
           MacOS) */
	
	return nil
}



func (wl *wildland)start() error {
	C.Py_Initialize()
//	defer C.Py_Finalize()

	goSocketPath := os.Getenv("XDG_RUNTIME_DIR") + "wlfuse.sock"
	log.Println("using control_server socket path: ", goSocketPath)
	socketPath := C.CString(goSocketPath)
	pySocketPath := C.PyUnicode_FromString(socketPath)
	defer C.free(unsafe.Pointer(socketPath))
	defer C.decref(pySocketPath)

	log.Println("going to dump module search path now")
	envdumpcmd := C.CString("import sys; print(sys.path);")
	C.PyRun_SimpleString(envdumpcmd)
	C.free(unsafe.Pointer(envdumpcmd))
	log.Println("just dumped module search path")

	mod,err := wl.importModule("wildland.go.fs")
	if err != nil {
		C.PyErr_Print()
		return err
	}

	pyfs := newPyObject(mod, "WildlandGoFS", pySocketPath)
	if pyfs == nil {
		C.PyErr_Print()
		return errors.New("failed to instantiate python fs")
	} else {
		//defer C.decref(pyfs) - leaving immeadiately we need to keep this object alive
		log.Println("invoking fs.start()")
		obj,_ := callPyMethod(pyfs, "start")
		C.decref(obj)
		log.Println("fs.start() invoked")
	}
	wl.fspy = pyfs
	wait_chan := make(chan struct{})
	log.Println("I'm leaving the scope of bridge now!!!")
	wl.save = C.PyEval_SaveThread()
	<- wait_chan
	return nil
}

func (wl *wildland)readdir(path string) ([]i_fs_object, error) {
	C.PyEval_RestoreThread(wl.save)
	defer func(){
		wl.save = C.PyEval_SaveThread()
	}()
	
	pyName := makePyString(path)
	defer C.decref(pyName)
	pyoffset := makePyLong(0)
	defer C.decref(pyoffset)
	
	res, err := callPyMethod(wl.fspy, "readdir", pyName, pyoffset)
	var rv []i_fs_object = nil
	if res != nil {
		defer C.decref(res)
		nelts := int(C.PySequence_Size(res))
		rv = make([]i_fs_object, 0, nelts)
		for i := 0 ;i < nelts; i++ {
			pyobj := C.PySequence_GetItem(res, C.long(i))
			ucs4chars := C.PyUnicode_GetLength(pyobj)
			ucs4str := C.PyUnicode_AsUCS4Copy(pyobj)
//			defer C.free(unsafe.Pointer(ucs4str))
			enc := utf32.UTF32(utf32.LittleEndian, utf32.IgnoreBOM)
			dec := enc.NewDecoder()
			gobytes := C.GoBytes(unsafe.Pointer(ucs4str), C.int(ucs4chars * C.long(4)))
			if utf8bytes, err := dec.Bytes(gobytes); err == nil {
				name := string(utf8bytes[:])
				obj := &wildland_dir { fs_object: fs_object {name: name} } // TODO: should be either file or dir composition
				obj.SetFS(wl.fs)
				wl.fs.pmap["/" + name] = obj
				log.Println("registering path ", name)
				rv = append(rv, obj)
			} else {
				return nil, err
			}
		}
	}
	
	return rv,err
}


func makePyString(str string) PyObjRef {
	cstr := C.CString(str)
	defer C.free(unsafe.Pointer(cstr))
	return C.PyUnicode_FromString(cstr)
}

func makePyLong(val int) PyObjRef {
	obj := C.PyLong_FromLong(C.long(val))
	if val >= -5 && val <= 256 {
		C.incref(obj)
	}
	return obj
}
