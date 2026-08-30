#!/bin/sh
set -eu

repo_url="https://github.com/watamario15/MkXTBWikiplexus.git"
revision="52f702cbd6635d9f91a7ead6641401acaf0e832d"
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir="$root/tools/MkXTBWikiplexus-src"
output="$root/tools/MkImageComplex-bin"
compat_dir="$root/scripts/mkimagecomplex-compat"

arch=$(uname -m)
if [ "$arch" != "aarch64" ] && [ "$arch" != "arm64" ]; then
  echo "warning: building on $arch (the intended Raspberry Pi target is aarch64)" >&2
fi

command -v g++ >/dev/null || { echo "g++ is required (sudo apt install g++)" >&2; exit 1; }
command -v pkg-config >/dev/null || { echo "pkg-config is required" >&2; exit 1; }
pkg-config --exists libxml-2.0 || { echo "libxml2-dev is required" >&2; exit 1; }

if [ ! -d "$source_dir/.git" ]; then
  git clone "$repo_url" "$source_dir"
fi
git -C "$source_dir" fetch --depth 1 origin "$revision"
git -C "$source_dir" checkout --detach "$revision"

mkdir -p "$root/tools"
# MkImageComplex includes the old project's precompiled headers, which pull in
# MeCab even though this target never uses it.  The compatibility include also
# supplies standard C++ headers that some translation units assumed the Xcode
# precompiled header had already loaded.
g++ -std=c++11 -O3 -DNDEBUG -D_LARGEFILE_SOURCE=1 -D_LARGEFILE64_SOURCE=1 \
  -D_FILE_OFFSET_BITS=64 -DJPGD_USE_SSE2=0 \
  -I"$compat_dir" -include "$compat_dir/preinclude.hpp" \
  $(pkg-config --cflags libxml-2.0) \
  "$source_dir/MkImageComplex/main.cpp" \
  "$source_dir/MkXTBWikiplexus/XTBDicDB.cpp" \
  "$source_dir/MkXTBWikiplexus/utils.cpp" \
  "$source_dir/RichgelJpeg/jpgd.cpp" \
  $(pkg-config --libs libxml-2.0) -o "$output"
chmod +x "$output"
echo "built: $output"
