import os
import sys
import time

def build_tokenizer():
    build_dir = "build"
    if not os.path.exists(build_dir):
        os.makedirs(build_dir)
    
    os.chdir(build_dir)
    print("Configuring CMake for cpp_fast_tokenizer...")
    os.system("cmake ..")
    print("Building project...")
    os.system("cmake --build . --config Release")
    
    print("\n--- Build Complete ---")
    print("Testing integration...")
    
    sys.path.append(os.path.join(os.path.abspath("."), "Release"))
    try:
        import fast_tokenizer_py
        tokenizer = fast_tokenizer_py.FastTokenizer()
        
        long_text = "主人你好！今天天气不错，记得多喝水。Hello World! " * 1000
        
        start = time.perf_counter()
        count = tokenizer.count_tokens(long_text)
        end = time.perf_counter()
        
        print("\n[SUCCESS] Tokenizer imported successfully.")
        print(f"Counted {count} tokens in {(end-start)*1000:.3f} ms for {len(long_text)} characters.")
        
        truncated = tokenizer.truncate_from_back(long_text, 10)
        print(f"Truncated sample (last 10 tokens): '{truncated.strip()}'")
        
    except ImportError as e:
        print(f"[ERROR] Failed to import fast_tokenizer_py: {e}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    build_tokenizer()
