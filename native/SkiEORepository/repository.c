#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winhttp.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "miniz_tinfl.h"

static HMODULE module;
static volatile LONG network_active;
static int sibling(wchar_t *path, const wchar_t *name) {
    if (!GetModuleFileNameW(module, path, MAX_PATH)) return 0;
    wchar_t *slash = wcsrchr(path, L'\\');
    if (!slash || (size_t)(slash - path) + wcslen(name) + 2 >= MAX_PATH) return 0;
    wcscpy(slash + 1, name);
    return 1;
}
static void status(const wchar_t *name, const char *message) {
    wchar_t path[MAX_PATH], temporary[MAX_PATH];
    if (!sibling(path, name)) return;
    swprintf(temporary, MAX_PATH, L"%ls.part", path);
    FILE *file = _wfopen(temporary, L"wb");
    if (file) { fputs(message, file); fclose(file); MoveFileExW(temporary, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH); }
}
/* Hash the running executable once, off the game thread. No Steam session,
   network access or private game memory is needed for build recognition. */
static volatile LONG identity_started;
static DWORD WINAPI game_identity_worker(void *unused) {
    (void)unused;
    wchar_t path[32768];
    unsigned char buffer[65536], digest[32];
    char result[68] = "ok ";
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    FILE *file = NULL;
    const char *failure = "error: cannot identify game executable";
    DWORD length = GetModuleFileNameW(NULL, path, 32768);
    if (!length || length >= 32768) goto done;
    file = _wfopen(path, L"rb");
    if (!file || BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0)
        || BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0)) goto done;
    size_t count;
    while ((count = fread(buffer, 1, sizeof(buffer), file)) != 0)
        if (BCryptHashData(hash, buffer, (ULONG)count, 0)) goto done;
    if (ferror(file) || BCryptFinishHash(hash, digest, sizeof(digest), 0)) goto done;
    for (unsigned i = 0; i < 32; ++i) sprintf(result + 3 + i * 2, "%02x", digest[i]);
    failure = result;
done:
    if (file) fclose(file);
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    status(L"game_identity.status", failure);
    return 0;
}
__declspec(dllexport) int skieo_game_identity(void *state) {
    (void)state;
    if (InterlockedCompareExchange(&identity_started, 1, 0) != 0) return 0;
    HANDLE worker = CreateThread(NULL, 0, game_identity_worker, NULL, 0, NULL);
    if (worker) CloseHandle(worker);
    else status(L"game_identity.status", "error: cannot start game version check");
    return 0;
}
static uint32_t crc32_bytes(const unsigned char *data, size_t size) {
    uint32_t table[256], crc = 0xffffffffU;
    for (uint32_t n = 0; n < 256; n++) {
        uint32_t value = n;
        for (int bit = 0; bit < 8; bit++) value = (value >> 1) ^ ((value & 1) ? 0xedb88320U : 0);
        table[n] = value;
    }
    for (size_t n = 0; n < size; n++) crc = table[(crc ^ data[n]) & 255] ^ (crc >> 8);
    return crc ^ 0xffffffffU;
}
__declspec(dllexport) int skieo_inflate(void *state) {
    (void)state;
    wchar_t path[MAX_PATH], output_path[MAX_PATH];
    uint32_t expected, checksum;
    unsigned char header[12], *source = NULL, *output = NULL;
    FILE *file = NULL;
    const char *failure = "error: invalid DEFLATE job";
    if (!sibling(path, L"inflate.job") || !sibling(output_path, L"inflate.response")) goto done;
    file = _wfopen(path, L"rb");
    if (!file || fread(header, 1, 12, file) != 12 || memcmp(header, "SKDF", 4)) goto done;
    memcpy(&expected, header + 4, 4); memcpy(&checksum, header + 8, 4);
    if (expected > 1024U * 1024U * 1024U) goto done;
    fseek(file, 0, SEEK_END); long length = ftell(file);
    if (length < 12 || length > 512L * 1024L * 1024L + 12) goto done;
    fseek(file, 12, SEEK_SET);
    source = malloc((size_t)length - 12 + 1); output = malloc((size_t)expected + 1);
    if (!source || !output) { failure = "error: DEFLATE allocation failed"; goto done; }
    if (fread(source, 1, (size_t)length - 12, file) != (size_t)length - 12) goto done;
    fclose(file); file = NULL;
    size_t produced = tinfl_decompress_mem_to_mem(output, (size_t)expected + 1, source, (size_t)length - 12, 0);
    if (produced != expected || crc32_bytes(output, produced) != checksum) { failure = "error: DEFLATE size or CRC mismatch"; goto done; }
    file = _wfopen(output_path, L"wb");
    if (!file || fwrite(output, 1, produced, file) != produced) { failure = "error: DEFLATE output failed"; goto done; }
    failure = "ok";
done:
    if (file) fclose(file);
    free(source); free(output);
    status(L"inflate.status", failure);
    return 0;
}

typedef struct Job { uint32_t maximum; char sha[65]; wchar_t url[4096]; } Job;
static DWORD WINAPI fetch(void *argument) {
    Job *job = argument;
    HINTERNET session = NULL, connection = NULL, request = NULL;
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    FILE *file = NULL;
    wchar_t output[MAX_PATH], staged[MAX_PATH], host[512], path[4096], extra[4096];
    const char *failure = "error: repository request failed";
    unsigned char digest[32], buffer[65536];
    char hex[65]; uint64_t total = 0;
    URL_COMPONENTS parts; ZeroMemory(&parts, sizeof(parts)); parts.dwStructSize = sizeof(parts);
    parts.lpszHostName = host; parts.dwHostNameLength = 512;
    parts.lpszUrlPath = path; parts.dwUrlPathLength = 4096;
    parts.lpszExtraInfo = extra; parts.dwExtraInfoLength = 4096;
    ULONGLONG start = GetTickCount64(), last_progress = start;
    char progress[64];
    snprintf(progress, sizeof(progress), "0/%u", job->maximum);
    status(L"network.progress", progress);
    if (!sibling(output, L"network.response")) goto done;
    swprintf(staged, MAX_PATH, L"%ls.part", output);
    if (!WinHttpCrackUrl(job->url, 0, 0, &parts) || parts.nScheme != INTERNET_SCHEME_HTTPS || parts.dwUserNameLength || parts.dwPasswordLength) { failure = "error: repository requires an HTTPS URL"; goto done; }
    if (parts.dwExtraInfoLength) {
        if (extra[0] != L'?' || wcschr(extra, L'#') || wcslen(path) + wcslen(extra) >= 4096) { failure = "error: invalid URL query"; goto done; }
        wcscat(path, extra);
    }
    session = WinHttpOpen(L"SkiEO-CustomMap/1.0", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) goto done;
    WinHttpSetTimeouts(session, 5000, 10000, 10000, 30000);
    connection = WinHttpConnect(session, host, parts.nPort, 0);
    if (!connection) goto done;
    request = WinHttpOpenRequest(connection, L"GET", path, NULL, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE);
    if (!request) goto done;
    DWORD redirects = WINHTTP_OPTION_REDIRECT_POLICY_NEVER;
    if (!WinHttpSetOption(request, WINHTTP_OPTION_REDIRECT_POLICY, &redirects, sizeof(redirects))) goto done;
    if (!WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) || !WinHttpReceiveResponse(request, NULL)) goto done;
    DWORD code = 0, code_size = sizeof(code);
    if (!WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX, &code, &code_size, WINHTTP_NO_HEADER_INDEX) || code != 200) { failure = "error: repository returned a non-200 response"; goto done; }
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) || BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0)) goto done;
    file = _wfopen(staged, L"wb"); if (!file) { failure = "error: cannot write download cache"; goto done; }
    DWORD read;
    while (WinHttpReadData(request, buffer, sizeof(buffer), &read)) {
        if (!read) {
            if (BCryptFinishHash(hash, digest, sizeof(digest), 0)) goto done;
            for (unsigned n = 0; n < 32; n++) sprintf(hex + n * 2, "%02x", digest[n]);
            if (job->sha[0] && strcmp(job->sha, hex)) { failure = "error: download SHA-256 mismatch"; goto done; }
            fclose(file); file = NULL;
            if (!MoveFileExW(staged, output, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) goto done;
            failure = "ok"; goto done;
        }
        total += read;
        if (total > job->maximum || GetTickCount64() - start > 180000) { failure = "error: repository size or time limit exceeded"; goto done; }
        if (fwrite(buffer, 1, read, file) != read || BCryptHashData(hash, buffer, read, 0)) { failure = "error: cannot save download"; goto done; }
        ULONGLONG now = GetTickCount64();
        if (now - last_progress >= 100) {
            snprintf(progress, sizeof(progress), "%llu/%u", (unsigned long long)total, job->maximum);
            status(L"network.progress", progress);
            last_progress = now;
        }
    }
done:
    if (file) fclose(file);
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    if (request) WinHttpCloseHandle(request);
    if (connection) WinHttpCloseHandle(connection);
    if (session) WinHttpCloseHandle(session);
    if (strcmp(failure, "ok") && sibling(output, L"network.response")) { swprintf(staged, MAX_PATH, L"%ls.part", output); DeleteFileW(staged); }
    free(job);
    InterlockedExchange(&network_active, 0);
    if (!strcmp(failure, "ok")) {
        snprintf(progress, sizeof(progress), "%llu/%llu", (unsigned long long)total, (unsigned long long)total);
        status(L"network.progress", progress);
    }
    status(L"network.status", failure);
    return 0;
}
__declspec(dllexport) int skieo_fetch(void *state) {
    (void)state;
    if (InterlockedCompareExchange(&network_active, 1, 0)) return 0;
    wchar_t path[MAX_PATH]; char magic[4], url[4096];
    Job *job = calloc(1, sizeof(Job)); FILE *file = NULL;
    if (!job || !sibling(path, L"network.job")) goto failure;
    file = _wfopen(path, L"rb");
    if (!file || fread(magic, 1, 4, file) != 4 || memcmp(magic, "SKRQ", 4) || fread(&job->maximum, 4, 1, file) != 1 || fread(job->sha, 1, 64, file) != 64) goto failure;
    size_t count = fread(url, 1, sizeof(url) - 1, file); url[count] = 0;
    fclose(file); file = NULL;
    if (!job->maximum || job->maximum > 512U * 1024U * 1024U || !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, url, -1, job->url, 4096)) goto failure;
    if (job->sha[0] == ' ') job->sha[0] = 0;
    HANDLE thread = CreateThread(NULL, 0, fetch, job, 0, NULL);
    if (!thread) goto failure;
    CloseHandle(thread); return 0;
failure:
    if (file) fclose(file);
    free(job); InterlockedExchange(&network_active, 0);
    status(L"network.status", "error: invalid network job or worker unavailable");
    return 0;
}
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) { module = instance; DisableThreadLibraryCalls(instance); }
    return TRUE;
}
