#pragma once

// Compatibility shim for MkImageComplex only.  Its legacy precompiled header
// includes <mecab.h>, but none of the source files built by our helper script
// uses the MeCab API.  Keeping this header empty avoids an unnecessary runtime
// and development dependency.
