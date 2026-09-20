.PHONY: all test clean
all:
	cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
	cmake --build build -j2
test: all
	ctest --test-dir build --output-on-failure
clean:
	cmake --build build --target clean
