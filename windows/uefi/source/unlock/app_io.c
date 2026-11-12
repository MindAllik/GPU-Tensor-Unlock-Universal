/* Modified 2026-10-21: experimental AD103 32GB GA102-pair port; see PORT-NOTES.txt. */
#include "app_io.h"
#include "compat/compat.h"
#include "format.h"
#include "local_profile.h"
#include "sha256.h"
#include <Protocol/BlockIo.h>
#include <Protocol/LoadedImage.h>
#include <Protocol/SimpleFileSystem.h>
#include <Guid/FileInfo.h>
static EFI_GUID LoadedGuid=EFI_LOADED_IMAGE_PROTOCOL_GUID,PathGuid=EFI_DEVICE_PATH_PROTOCOL_GUID,
  FsGuid=EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID,InfoGuid=EFI_FILE_INFO_ID,
  BlockIoGuid=EFI_BLOCK_IO_PROTOCOL_GUID;
static EFI_SYSTEM_TABLE *Table;
static EFI_HANDLE BootDeviceHandle;
static EFI_FILE_PROTOCOL *Root,*Parent,*Run,*Report;
static BOOLEAN LogFault;
BOOLEAN GuScreenDetached;
typedef struct {const char *name;CHAR16 *file;UINTN size;const char *hash;} ASSET_SPEC;
#if defined(GU_ARCH_TURING) && GU_ARCH_TURING
#ifndef GU_TU102_BOOTER_SIZE
#define GU_TU102_BOOTER_SIZE 59224U
#endif
#ifndef GU_TU102_BOOTER_HASH
#define GU_TU102_BOOTER_HASH "51507de61777cf46f3703a084cdfa896c21f6bc0c8af8f245bd09b2e9c49bf54"
#endif
#ifndef GU_TU102_GSP_SIZE
#define GU_TU102_GSP_SIZE 29352832U
#endif
#ifndef GU_TU102_GSP_HASH
#define GU_TU102_GSP_HASH "73065619db9ec921d19fc4e519dd04d91a9199b525eaca9b257b89fb8c5ec52c"
#endif
#ifndef GU_TU102_BOOT_SIZE
#define GU_TU102_BOOT_SIZE 4096U
#endif
#ifndef GU_TU102_BOOT_HASH
#define GU_TU102_BOOT_HASH "8765694cd38beaa4e2b8b1b83a31fb7aee6cb9d8b7c6bc7a86e6d931a3a056c2"
#endif
#ifndef GU_TU102_BOOT_DESC_SIZE
#define GU_TU102_BOOT_DESC_SIZE 76U
#endif
#ifndef GU_TU102_BOOT_DESC_HASH
#define GU_TU102_BOOT_DESC_HASH "9e7cca2cfdc5ce601b0adba39967850046108df6c2d23fff95578ca3f0ccbe01"
#endif
static const ASSET_SPEC Specs[]={
 {"gpu-unlock/610.43.03/booter_load_tu102.bin",L"ASSETS\\booter_load_tu102.bin",GU_TU102_BOOTER_SIZE,GU_TU102_BOOTER_HASH},
 {"gpu-unlock/610.43.03/v67-tu102-610.43.03.bin",L"ASSETS\\v67-tu102-610.43.03.bin",64000,"54513477ba4da9922fe00678ae390b1ec5136353989b23238c3524a69c7a8024"},
 {"gpu-unlock/610.43.03/gsp_tu10x.bin",L"ASSETS\\gsp_tu10x.bin",GU_TU102_GSP_SIZE,GU_TU102_GSP_HASH},
 {"gpu-unlock/610.43.03/gsp_boot_tu102.bin",L"ASSETS\\gsp_boot_tu102.bin",GU_TU102_BOOT_SIZE,GU_TU102_BOOT_HASH},
 {"gpu-unlock/610.43.03/gsp_boot_desc_tu102.bin",L"ASSETS\\gsp_boot_desc_tu102.bin",GU_TU102_BOOT_DESC_SIZE,GU_TU102_BOOT_DESC_HASH}
};
#elif !defined(GU_ARCH_ADA) || GU_ARCH_ADA
static const ASSET_SPEC Specs[]={
 {"gpu-unlock/610.43.03/booter_load_ad102.bin",L"ASSETS\\booter_load_ad102.bin",57672,"6ee05b20e1dc244c08c052f36ef28469b8d09f4955d1fe33e48a179e11a7fd49"},
 {"gpu-unlock/610.43.03/v67-ad102-610.43.03-four-plm.bin",L"ASSETS\\v67-ad102-610.43.03-four-plm.bin",64000,"44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb"},
 {"gpu-unlock/610.43.03/gsp_ga10x.bin",L"ASSETS\\gsp_ga10x.bin",84277400,"572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a"},
 {"gpu-unlock/610.43.03/gsp_boot_ad102.bin",L"ASSETS\\gsp_boot_ad102.bin",36864,"45d6335a8185d6ff13e8d1484cea73f68d3d13aa1c19dc080ed1c3482dd5bac0"},
 {"gpu-unlock/610.43.03/gsp_boot_desc_ad102.bin",L"ASSETS\\gsp_boot_desc_ad102.bin",84,"83f8f3f1f5f9496e0ea8fc7103c2beb64d0b6de2f5ffe725f13514de5a95fa42"}
};
#else
static const ASSET_SPEC Specs[]={
 {"gpu-unlock/610.43.03/booter_load_ga102.bin",L"ASSETS\\booter_load_ga102.bin",61256,"056cbc064a888f80717726c54d7f64fcd68044d123870c95a74f37f4975dcaa4"},
 {"gpu-unlock/610.43.03/v67-ga102-610.43.03.bin",L"ASSETS\\v67-ga102-610.43.03.bin",64000,"2a0aa1f86d0b6afff5214d641d87d46dc98ef06ed908ff05d0ddbad5ffb7e197"},
 {"gpu-unlock/610.43.03/gsp_ga10x.bin",L"ASSETS\\gsp_ga10x.bin",84277400,"572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a"},
 {"gpu-unlock/610.43.03/gsp_boot_ga102.bin",L"ASSETS\\gsp_boot_ga102.bin",24576,"3df651acb174fd5f5561a1996965b192f50c5d763168446ed0d4ead19d895768"},
 {"gpu-unlock/610.43.03/gsp_boot_desc_ga102.bin",L"ASSETS\\gsp_boot_desc_ga102.bin",84,"cc5a3fc1f4c47f2fe107b1b68f0176d8a448e6dec84b575e5560ccef5262bf15"}
};
#endif
static VOID LogError(VOID){LogFault=TRUE;if(Gu.armed)Gu.fault=TRUE;}
VOID GuConsole(const char *Text) {
  if(GuScreenDetached)return;
  if(!Table || !Table->ConOut || !Table->ConOut->OutputString)return;
  while(*Text) {
    CHAR16 line[128];UINTN n=0;
    while(*Text && n<126) {
      UINT8 ch=(UINT8)*Text++;
      if(ch=='\n')line[n++]='\r';
      line[n++]=(ch>=0x80U)?(CHAR16)'-':(CHAR16)ch;
    }
    line[n]=0;
    /* Never latch LogFault on console OutputString glyph warnings/errors;
       REPORT.TXT logging and hardware unlock must not be aborted by ConOut. */
    Table->ConOut->OutputString(Table->ConOut,line);
  }
}
VOID GuLogText(const char *Text) {
  GuConsole(Text);
  if(!Report || LogFault){LogError();return;}
  UINTN expected=strlen(Text),written=expected;
  EFI_STATUS status=Report->Write(Report,&written,(VOID *)Text);
  if(EFI_ERROR(status) || written!=expected || EFI_ERROR(Report->Flush(Report)))LogError();
  else {
    if(Run)Run->Flush(Run);
    if(Parent)Parent->Flush(Parent);
    if(Root)Root->Flush(Root);
  }
}
VOID GuLog(const char *Format,...) {
  char text[1024];va_list args;va_start(args,Format);
  size_t n=GuFormatV(text,sizeof(text),Format,args);va_end(args);
  if(n>=sizeof(text)){LogError();GuConsole("Log format or length error.\n");return;}
  GuLogText(text);
}
BOOLEAN GuLogReady(VOID){return Report && !LogFault;}
VOID GuCheckpointReport(VOID) {
  if(!Report || !Run || LogFault || Gu.retained)return;
  Report->Flush(Report);
  Run->Flush(Run);
  if(Parent)Parent->Flush(Parent);
  if(Root)Root->Flush(Root);
  /* Only attempt Close+reopen if opening a second handle succeeds first (auto-degrade
     for #198/#122 firmware where reopen after Close is refused by EnhancedFatDxe). */
  if(Report->SetPosition) {
    EFI_FILE_PROTOCOL *probe=NULL;
    if(!EFI_ERROR(Run->Open(Run,&probe,L"REPORT.TXT",EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE,0)) && probe) {
      if(!EFI_ERROR(probe->SetPosition(probe,0xffffffffffffffffULL))) {
        Report->Close(Report);
        Report=probe;
        Run->Flush(Run);
        if(Parent)Parent->Flush(Parent);
        if(Root)Root->Flush(Root);
      } else {
        probe->Close(probe);
      }
    }
  }
}
static BOOLEAN UsbPath(EFI_HANDLE Handle) {
  EFI_DEVICE_PATH_PROTOCOL *path=NULL;
  if(EFI_ERROR(Table->BootServices->HandleProtocol(Handle,&PathGuid,(VOID **)&path)) || !path)return FALSE;
  UINTN total=0;BOOLEAN usb=FALSE;
  EFI_BLOCK_IO_PROTOCOL *bio=NULL;
  if(!EFI_ERROR(Table->BootServices->HandleProtocol(Handle,&BlockIoGuid,(VOID **)&bio)) &&
    bio && bio->Media && bio->Media->RemovableMedia)usb=TRUE;
  for(UINTN nodes=0;nodes<64 && total+4<=4096;nodes++) {
    UINTN n=path->Length[0]+((UINTN)path->Length[1]<<8);
    if(n<4 || n>4096-total)return FALSE;
    if(path->Type==MESSAGING_DEVICE_PATH &&
      ((path->SubType==MSG_USB_DP && n>=sizeof(USB_DEVICE_PATH)) ||
       (path->SubType==MSG_USB_CLASS_DP && n>=sizeof(USB_CLASS_DEVICE_PATH)) ||
       (path->SubType==MSG_USB_WWID_DP && n>=sizeof(USB_WWID_DEVICE_PATH)) ||
       (path->SubType==MSG_SD_DP && n>=sizeof(SD_DEVICE_PATH)) ||
       (path->SubType==MSG_EMMC_DP && n>=sizeof(EMMC_DEVICE_PATH)) ||
       (path->SubType==MSG_UFS_DP && n>=sizeof(UFS_DEVICE_PATH))))usb=TRUE;
    if(path->Type==BBS_DEVICE_PATH && path->SubType==BBS_BBS_DP &&
      n>=sizeof(BBS_BBS_DEVICE_PATH) && ((BBS_BBS_DEVICE_PATH *)path)->DeviceType==BBS_TYPE_USB)usb=TRUE;
    if(path->Type==END_DEVICE_PATH_TYPE)return usb && n==4 && path->SubType==END_ENTIRE_DEVICE_PATH_SUBTYPE;
    total+=n;path=(VOID *)((UINT8 *)path+n);
  }
  return FALSE;
}
static BOOLEAN IsZeroGuid(const EFI_GUID *G) {
  static const EFI_GUID zero={0,0,0,{0,0,0,0,0,0,0,0}};
  return memcmp(G,&zero,sizeof(zero))==0;
}
static BOOLEAN EspGuidPath(EFI_HANDLE Handle,const EFI_GUID *Want,UINT32 Partition) {
  if(IsZeroGuid(Want))return FALSE;
  EFI_DEVICE_PATH_PROTOCOL *path=NULL;
  if(EFI_ERROR(Table->BootServices->HandleProtocol(Handle,&PathGuid,(VOID **)&path)) || !path)return FALSE;
  UINTN off=0;
  for(UINTN i=0;i<128 && off<=4092;i++) {
    EFI_DEVICE_PATH_PROTOCOL *node=(VOID*)((UINT8*)path+off);
    UINTN len=node->Length[0]+((UINTN)node->Length[1]<<8);
    if(len<4 || len>4096-off)return FALSE;
    if(node->Type==MEDIA_DEVICE_PATH && node->SubType==MEDIA_HARDDRIVE_DP) {
      if(len!=sizeof(HARDDRIVE_DEVICE_PATH))return FALSE;
      HARDDRIVE_DEVICE_PATH *hd=(VOID*)node;
      return hd->SignatureType==2 && hd->MBRType==2 && (Partition==0 || hd->PartitionNumber==Partition) &&
        !memcmp(hd->Signature,Want,sizeof(*Want));
    }
    if(node->Type==END_DEVICE_PATH_TYPE)return FALSE;
    off+=len;
  }
  return FALSE;
}
/* Byte-identical device paths mean the SAME volume seen through two handles;
   the volume we booted from must never be adopted as a payload candidate,
   even when a profile leaves both GUID defaults at zero. */
static BOOLEAN SameDevicePath(EFI_HANDLE A,EFI_HANDLE B) {
  EFI_DEVICE_PATH_PROTOCOL *a=NULL,*b=NULL;
  if(EFI_ERROR(Table->BootServices->HandleProtocol(A,&PathGuid,(VOID **)&a)) ||
    EFI_ERROR(Table->BootServices->HandleProtocol(B,&PathGuid,(VOID **)&b)) || !a || !b)return FALSE;
  UINTN off=0;
  for(UINTN i=0;i<128 && off<=4092;i++) {
    EFI_DEVICE_PATH_PROTOCOL *na=(VOID*)((UINT8*)a+off);
    EFI_DEVICE_PATH_PROTOCOL *nb=(VOID*)((UINT8*)b+off);
    UINTN len_a=na->Length[0]+((UINTN)na->Length[1]<<8);
    UINTN len_b=nb->Length[0]+((UINTN)nb->Length[1]<<8);
    if(len_a<4 || len_a>4096-off || len_b<4 || len_b>4096-off)return FALSE;
    if(len_a!=len_b || na->Type!=nb->Type || na->SubType!=nb->SubType)return FALSE;
    if(memcmp(na,nb,len_a)!=0)return FALSE;
    if(na->Type==END_DEVICE_PATH_TYPE)return na->SubType==END_ENTIRE_DEVICE_PATH_SUBTYPE;
    off+=len_a;
  }
  return FALSE;
}
BOOLEAN GuLocalEsp(EFI_HANDLE Handle) {
  static const EFI_GUID guid={KOH_WINDOWS_ESP_GUID};
  /* Match the unique 128-bit GPT Partition GUID and optional KOH_WINDOWS_ESP_PART (0 = wildcard). */
  return EspGuidPath(Handle,&guid,KOH_WINDOWS_ESP_PART);
}
BOOLEAN GuIsBootVolume(EFI_HANDLE Handle) {
  if(!BootDeviceHandle || !Handle)return FALSE;
  return Handle==BootDeviceHandle || SameDevicePath(Handle,BootDeviceHandle);
}
static BOOLEAN GuPayloadEsp(EFI_HANDLE Handle) {
  static const EFI_GUID guid={KOH_PAYLOAD_ESP_GUID};
  /* Partition NUMBER is not pinned: diskpart renumbered the payload from the
     planned part 5 to part 4 after the C: shrink (measured 2026-10-26, the
     hardware run failed on the stale number). The GPT GUID is unique and
     authoritative; 0 = accept any index. */
  return EspGuidPath(Handle,&guid,0);
}
static EFI_STATUS Metadata(EFI_FILE_PROTOCOL *File,BOOLEAN Directory,UINTN Expected) {
  union {EFI_FILE_INFO info;UINT8 bytes[512];} data;UINTN n=sizeof(data);
  EFI_STATUS status=File->GetInfo(File,&InfoGuid,&n,&data);
  if(EFI_ERROR(status))return status;
  if(n<SIZE_OF_EFI_FILE_INFO || n>sizeof(data) || data.info.Size>n || data.info.Size<SIZE_OF_EFI_FILE_INFO ||
    !!(data.info.Attribute&EFI_FILE_DIRECTORY)!=!!Directory ||
    (!Directory && data.info.FileSize!=Expected))return EFI_COMPROMISED_DATA;
  return EFI_SUCCESS;
}
EFI_STATUS GuIoOpen(EFI_HANDLE Image,EFI_SYSTEM_TABLE *St) {
  Table=St;BootDeviceHandle=NULL;Root=Parent=Run=Report=NULL;LogFault=FALSE;memset(GuAssets,0,sizeof(GuAssets));
  EFI_LOADED_IMAGE_PROTOCOL *loaded=NULL;EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *fs=NULL;
  EFI_STATUS status=Table->BootServices->HandleProtocol(Image,&LoadedGuid,(VOID **)&loaded);
  if(EFI_ERROR(status) || !loaded || !(UsbPath(loaded->DeviceHandle) || GuLocalEsp(loaded->DeviceHandle) ||
    GuPayloadEsp(loaded->DeviceHandle)))return EFI_UNSUPPORTED;
  BootDeviceHandle=loaded->DeviceHandle;
  status=Table->BootServices->HandleProtocol(loaded->DeviceHandle,&FsGuid,(VOID **)&fs);
  if(EFI_ERROR(status) || !fs)return EFI_UNSUPPORTED;
  status=fs->OpenVolume(fs,&Root);if(EFI_ERROR(status) || !Root)return EFI_DEVICE_ERROR;
  BOOLEAN esp=GuLocalEsp(loaded->DeviceHandle);
  status=Root->Open(Root,&Parent,L"\\GPU-UNLOCK",EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE,0);
  if(status==EFI_NOT_FOUND && esp) {
    /* ESP boot: the ESP only holds the loader; the payload volume keeps the
       work tree. Mirror PreloadWindows: find it by its pinned GUID and accept
       it only when EXACTLY one volume matches — an ambiguous GPT (two volumes
       sharing the GUID, e.g. after a disk clone) must not be adopted. */
    EFI_HANDLE *hs=NULL;UINTN n=0,matches=0,chosen=0;
    status=Table->BootServices->LocateHandleBuffer(ByProtocol,&FsGuid,NULL,&n,&hs);
    if(EFI_ERROR(status) || !hs || n>256) {if(hs)Table->BootServices->FreePool(hs);return EFI_NOT_FOUND;}
    for(UINTN i=0;i<n;i++) {
      if(SameDevicePath(hs[i],loaded->DeviceHandle) || !GuPayloadEsp(hs[i]))continue;
      matches++;chosen=i;if(matches>1)break;
    }
    if(matches>1) {Table->BootServices->FreePool(hs);return EFI_NO_MAPPING;}
    if(matches==1) {
      EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *pfs=NULL;EFI_FILE_PROTOCOL *proot=NULL,*pparent=NULL;
      status=Table->BootServices->HandleProtocol(hs[chosen],&FsGuid,(VOID **)&pfs);
      if(EFI_ERROR(status) || !pfs)status=EFI_DEVICE_ERROR;
      else status=pfs->OpenVolume(pfs,&proot);
      if(EFI_ERROR(status) || !proot)status=EFI_DEVICE_ERROR;
      if(!EFI_ERROR(status))status=proot->Open(proot,&pparent,L"\\GPU-UNLOCK",EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE,0);
      if(EFI_ERROR(status) || !pparent) {
        if(pparent)pparent->Close(pparent);
        if(proot && proot!=pparent)proot->Close(proot);
        Table->BootServices->FreePool(hs);
        return EFI_ERROR(status)?status:EFI_DEVICE_ERROR;
      }
      status=Root->Close(Root);
      if(EFI_ERROR(status)) {
        pparent->Close(pparent);proot->Close(proot);Root=NULL;
        Table->BootServices->FreePool(hs);return EFI_DEVICE_ERROR;
      }
      Root=proot;Parent=pparent;status=EFI_SUCCESS;
    }
    Table->BootServices->FreePool(hs);
    if(EFI_ERROR(status))return EFI_NOT_FOUND;
  }
  if(EFI_ERROR(status) || !Parent)return EFI_NOT_FOUND;
  status=Metadata(Parent,TRUE,0);if(EFI_ERROR(status))return status;
  for(UINTN slot=0;slot<100;slot++) {
    CHAR16 name[]=L"RUN00";name[3]=(CHAR16)('0'+slot/10);name[4]=(CHAR16)('0'+slot%10);
    EFI_FILE_PROTOCOL *existing=NULL;
    status=Parent->Open(Parent,&existing,name,EFI_FILE_MODE_READ,0);
    if(!EFI_ERROR(status)) {
      if(!existing || EFI_ERROR(existing->Close(existing)))return EFI_DEVICE_ERROR;continue;
    }
    if(status!=EFI_NOT_FOUND)return status;
    status=Parent->Open(Parent,&Run,name,EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE|EFI_FILE_MODE_CREATE,EFI_FILE_DIRECTORY);
    if(EFI_ERROR(status) || !Run)return EFI_DEVICE_ERROR;
    status=Metadata(Run,TRUE,0);if(EFI_ERROR(status))return status;
    status=Run->Open(Run,&existing,L"REPORT.TXT",EFI_FILE_MODE_READ,0);
    if(!EFI_ERROR(status)){if(existing)existing->Close(existing);return EFI_ALREADY_STARTED;}
    if(status!=EFI_NOT_FOUND)return status;
    status=Run->Open(Run,&Report,L"REPORT.TXT",EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE|EFI_FILE_MODE_CREATE,0);
    if(EFI_ERROR(status) || !Report)return EFI_DEVICE_ERROR;
    GuLog("NVIDIA GPU TENSOR UNLOCK / UEFI PRE-BOOT TRANSACTION v%s\nRUN%02u\nRUN_ID=RUN%02u VERSION=%s BOARD_ID=%#x SUBSYSTEM=%#x BDF=%u:%u:%u.%u ARCH=%s\n[STAGE 1/3] PREFLIGHT & ASSET LOADING: verifying VBIOS and reading firmware from USB... Please wait (do NOT press keys yet). Confirmation mode=%s.\n",
      GU_APP_VERSION,(unsigned)slot,(unsigned)slot,GU_APP_VERSION,(unsigned)GU_BOARD_ID,(unsigned)GU_BOARD_SUBSYSTEM,
      (unsigned)GU_BOARD_SEGMENT,(unsigned)GU_BOARD_BUS,(unsigned)GU_BOARD_DEVICE,(unsigned)GU_BOARD_FUNCTION,
      GU_ARCH_TURING?"TURING":(GU_ARCH_ADA?"ADA":"AMPERE"),KOH_UNATTENDED_AUTOFIRE?"unattended":"manual");
    GuLogText("PIO readback is not an execution gate. This path does not independently verify TCM contents; FWSEC scratch/WPR results are required.\n");
    return GuLogReady()?EFI_SUCCESS:EFI_DEVICE_ERROR;
  }
  return EFI_VOLUME_FULL;
}
EFI_STATUS GuSavePromDump(const VOID *Data,UINTN Size) {
  if(!Run || !Data || Size!=1048576)return EFI_INVALID_PARAMETER;
  EFI_FILE_PROTOCOL *file=NULL;
  EFI_STATUS status=Run->Open(Run,&file,L"PROM.BIN",EFI_FILE_MODE_READ,0);
  if(!EFI_ERROR(status)) {
    if(file)file->Close(file);
    return EFI_ALREADY_STARTED;
  }
  if(status!=EFI_NOT_FOUND)return status;
  status=Run->Open(Run,&file,L"PROM.BIN",EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE|EFI_FILE_MODE_CREATE,0);
  if(EFI_ERROR(status) || !file)return EFI_ERROR(status)?status:EFI_DEVICE_ERROR;
  UINTN written=Size;
  status=file->Write(file,&written,(VOID *)Data);
  if(!EFI_ERROR(status) && written!=Size)status=EFI_BAD_BUFFER_SIZE;
  if(!EFI_ERROR(status))status=file->Flush(file);
  EFI_STATUS closed=file->Close(file);
  return EFI_ERROR(status)?status:closed;
}
EFI_STATUS GuLoadAssets(VOID) {
  static const char *const load_steps[5]={
    "[LOADING 1/5] Reading Booter Load ucode from USB...\n",
    "[LOADING 2/5] Reading V67 SEC2 payload from USB...\n",
    "[LOADING 3/5] Reading GSP firmware image (46-84 MB, takes 5-15s on USB)...\n",
    "[LOADING 4/5] Reading GSP RM Boot ucode from USB...\n",
    "[LOADING 5/5] Reading GSP Boot descriptor from USB...\n"
  };
  for(UINTN i=0;i<5;i++) {
    GuConsole(load_steps[i]);
    EFI_FILE_PROTOCOL *file=NULL;const ASSET_SPEC *spec=&Specs[i];
    UINTN spec_size=spec->size;const char *spec_hash=spec->hash;
#if defined(GU_GA102_GSP_SIZE) && defined(GU_GA102_GSP_HASH)
    if(i==2 && !(GU_ARCH_TURING)){spec_size=GU_GA102_GSP_SIZE;spec_hash=GU_GA102_GSP_HASH;}
#endif
    EFI_STATUS status=Parent->Open(Parent,&file,spec->file,EFI_FILE_MODE_READ,0);
    if(EFI_ERROR(status) || !file)return EFI_NOT_FOUND;
    status=Metadata(file,FALSE,spec_size);
    UINT8 *data=NULL;
    if(!EFI_ERROR(status)) {
      data=GuAlloc(spec_size);if(!data)status=EFI_OUT_OF_RESOURCES;
    }
    for(UINTN done=0;!EFI_ERROR(status) && done<spec_size;) {
      UINTN n=spec_size-done;if(n>1048576)n=1048576;UINTN want=n;
      status=file->Read(file,&n,data+done);
      if(!EFI_ERROR(status) && n!=want)status=EFI_END_OF_FILE;done+=n;
    }
    EFI_STATUS closed=file->Close(file);if(!EFI_ERROR(status))status=closed;
    if(!EFI_ERROR(status) && !GuHashMatches(data,spec_size,spec_hash))status=EFI_CRC_ERROR;
    if(EFI_ERROR(status)){GuFree(data);return status;}
    GuAssets[i].name=spec->name;GuAssets[i].firmware.data=data;GuAssets[i].firmware.size=spec_size;
    GuLog("asset verified: %s bytes=%zu sha256=%s\n",spec->name,(size_t)spec_size,spec_hash);
    if(!GuLogReady())return EFI_DEVICE_ERROR;
  }
  return EFI_SUCCESS;
}
VOID GuReleaseAssets(VOID) {
  if(!GuSafeToReturn())return;
  for(UINTN i=0;i<5;i++){GuFree((VOID *)GuAssets[i].firmware.data);memset(&GuAssets[i],0,sizeof(GuAssets[i]));}
}
VOID GuCloseLogForHalt(VOID) {
  EFI_FILE_PROTOCOL **files[]={&Report,&Run,&Parent,&Root};
  BOOLEAN saved_retained=Gu.retained;
  Gu.retained=FALSE;
  BootDeviceHandle=NULL;
  for(UINTN i=0;i<4;i++)if(*files[i]) {
    EFI_FILE_PROTOCOL *file=*files[i];*files[i]=NULL;
    file->Flush(file);
    file->Close(file);
  }
  Gu.retained=saved_retained;
}
EFI_STATUS GuIoClose(VOID) {
  EFI_FILE_PROTOCOL **files[]={&Report,&Run,&Parent,&Root};EFI_STATUS result=EFI_SUCCESS;
  if(!GuSafeToReturn())return EFI_ACCESS_DENIED;
  BootDeviceHandle=NULL;
  for(UINTN i=0;i<4;i++)if(*files[i]) {
    /* EFI_FILE_PROTOCOL.Close invalidates the handle even on error; close all handles and preserve first error. */
    EFI_FILE_PROTOCOL *file=*files[i];*files[i]=NULL;
    EFI_STATUS status=file->Close(file);
    if(EFI_ERROR(status) && !EFI_ERROR(result))result=status;
  }
  return result;
}
