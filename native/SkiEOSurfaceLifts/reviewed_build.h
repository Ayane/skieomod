/* Ski-E-O 26143813, SHA256 831667e59b6e64df1baecd543d98c719d5f8219ce1f3ac9648a641887dbe135f.
   Entire reviewed animation classifier, including field reads and branches. */
#define ANIMATION_RVA 0x51e4730u
#define ANIMATION_SIZE 0x30fu
#define ANIMATION_HASH UINT64_C(0x542fd3cdb5badd56)
#define STAMP_RVA 0x559bad0u
#define STAMP_SIZE 0x323u
#define STAMP_HASH UINT64_C(0x9ed6bc2c758a8347)

#define GUEST_RENDER_RVA 0x5276180u
#define GUEST_RENDER_SIZE 0x1127u
#define GUEST_RENDER_HASH UINT64_C(0xb2140d55efdb7dd7)

/* 26178224: all three full functions have identical instructions and field
   offsets after normalizing address operands; full relocated bytes guarded. */
#define ANIMATION_NEW_RVA 0x51e6900u
#define ANIMATION_NEW_HASH UINT64_C(0x3e16b8c1fe55c913)
#define STAMP_NEW_RVA 0x55a2c60u
#define STAMP_NEW_HASH UINT64_C(0xb9032b41300f92e8)
#define GUEST_RENDER_NEW_RVA 0x5279320u
#define GUEST_RENDER_NEW_HASH UINT64_C(0xb139919080280501)

/* 26178224: controller's Clear Snow call; complete circular wrapper and
   oriented implementation, including all chained unwind regions. */
#define SNOW_CLEAR_RVA 0x52af230u
#define SNOW_CLEAR_SIZE 0x64u
#define SNOW_CLEAR_HASH UINT64_C(0x25dce71dde26bf61)
#define SNOW_CLEAR_CORE_RVA 0x52b7480u
#define SNOW_CLEAR_CORE_SIZE 0x7fau
#define SNOW_CLEAR_CORE_HASH UINT64_C(0x1ad9d5a5f51c53b8)
