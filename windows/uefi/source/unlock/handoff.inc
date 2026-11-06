#include "local_profile.h"
/* Modified 2026-10-21: experimental AD103 32GB GA102-pair port; see PORT-NOTES.txt. */
/* Derived from the v0.3 handoff path exercised on this user's single AD103. */
#include <Protocol/LoadedImage.h>
#include <Protocol/SimpleFileSystem.h>
static EFI_GUID FsGuid=EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID,LoadedGuid=EFI_LOADED_IMAGE_PROTOCOL_GUID;
static const CHAR16 WindowsPath[]=L"\\EFI\\Microsoft\\Boot\\bootmgfw.efi";
static EFI_HANDLE WindowsImage,WindowsVolume;
static EFI_DEVICE_PATH_PROTOCOL *WindowsDevicePath;
static EFI_STATUS MakeWindowsPath(VOID) {
  EFI_DEVICE_PATH_PROTOCOL *base=NULL;
  EFI_STATUS s=Gu.bs->HandleProtocol(WindowsVolume,&PathGuid,(VOID**)&base);
  if(EFI_ERROR(s)||!base)return EFI_NOT_FOUND;
  UINTN off=0;BOOLEAN end=FALSE;
  for(UINTN i=0;i<128 && off<=4092;i++) {
    EFI_DEVICE_PATH_PROTOCOL *n=(VOID*)((UINT8*)base+off);
    UINTN len=n->Length[0]+((UINTN)n->Length[1]<<8);
    if(len<4||len>4096-off)return EFI_COMPROMISED_DATA;
    if(n->Type==END_DEVICE_PATH_TYPE) {
      if(n->SubType!=END_ENTIRE_DEVICE_PATH_SUBTYPE||len!=4)return EFI_UNSUPPORTED;
      end=TRUE;break;
    }
    off+=len;
  }
  if(!end)return EFI_COMPROMISED_DATA;
  UINTN node=4+sizeof(WindowsPath),total=off+node+4;
  UINT8 *b=GuAlloc(total);if(!b)return EFI_OUT_OF_RESOURCES;
  memcpy(b,base,off);b[off]=MEDIA_DEVICE_PATH;b[off+1]=MEDIA_FILEPATH_DP;
  b[off+2]=(UINT8)node;b[off+3]=(UINT8)(node>>8);memcpy(b+off+4,WindowsPath,sizeof(WindowsPath));
  b[off+node]=END_DEVICE_PATH_TYPE;b[off+node+1]=END_ENTIRE_DEVICE_PATH_SUBTYPE;b[off+node+2]=4;
  WindowsDevicePath=(VOID*)b;return EFI_SUCCESS;
}
static EFI_STATUS ProbeWindowsBootVolume(EFI_HANDLE Handle,UINTN *Found) {
  EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *fs=NULL;EFI_FILE_PROTOCOL *root=NULL,*file=NULL;
  EFI_STATUS s=EFI_SUCCESS,x=Gu.bs->HandleProtocol(Handle,&FsGuid,(VOID**)&fs);
  if(!EFI_ERROR(x)&&fs)x=fs->OpenVolume(fs,&root);
  if(EFI_ERROR(x)||!root)return EFI_DEVICE_ERROR;
  x=root->Open(root,&file,(CHAR16*)WindowsPath,EFI_FILE_MODE_READ,0);
  if(!EFI_ERROR(x)&&file) {
    UINT8 mz[2];UINTN bytes=2;EFI_STATUS y=file->Read(file,&bytes,mz);
    EFI_STATUS closed=file->Close(file);
    if(EFI_ERROR(y)||EFI_ERROR(closed)||bytes!=2||mz[0]!='M'||mz[1]!='Z')s=EFI_COMPROMISED_DATA;
    else {(*Found)++;WindowsVolume=Handle;}
  } else if(x!=EFI_NOT_FOUND)s=EFI_DEVICE_ERROR;
  x=root->Close(root);if(EFI_ERROR(x))s=x;
  return s;
}
/* Select the Windows ESP queried from this local machine, with automatic non-boot
   volume scan fallback when KOH_WINDOWS_ESP_GUID is AUTO (all-zero) or changed. */
static EFI_STATUS PreloadWindows(VOID) {
  EFI_HANDLE *h=NULL;UINTN n=0,found=0;
  EFI_STATUS s=Gu.bs->LocateHandleBuffer(ByProtocol,&FsGuid,NULL,&n,&h);
  if(EFI_ERROR(s))return s;
  if(!h||n>256){GuFree(h);return EFI_COMPROMISED_DATA;}
  for(UINTN i=0;i<n;i++) {
    if(!GuLocalEsp(h[i]))continue;
    s=ProbeWindowsBootVolume(h[i],&found);
    if(EFI_ERROR(s))break;
  }
  if(!EFI_ERROR(s) && found==0) {
    for(UINTN i=0;i<n;i++) {
      if(GuLocalEsp(h[i]) || GuIsBootVolume(h[i]))continue;
      s=ProbeWindowsBootVolume(h[i],&found);
      if(EFI_ERROR(s))break;
    }
  }
  GuFree(h);GuLog("Windows candidates=%zu status=%#llx\n",(size_t)found,(unsigned long long)s);
  if(EFI_ERROR(s))return s;
  if(found!=1)return found?EFI_NO_MAPPING:EFI_NOT_FOUND;
  s=MakeWindowsPath();if(EFI_ERROR(s))return s;
  s=Gu.bs->LoadImage(FALSE,Gu.image,WindowsDevicePath,NULL,0,&WindowsImage);
  GuLog("Windows LoadImage=%#llx\n",(unsigned long long)s);
  if(EFI_ERROR(s))return s;
  EFI_LOADED_IMAGE_PROTOCOL *li=NULL;
  s=Gu.bs->HandleProtocol(WindowsImage,&LoadedGuid,(VOID**)&li);
  if(EFI_ERROR(s)||!li||li->DeviceHandle!=WindowsVolume||li->ImageCodeType!=EfiLoaderCode)return EFI_COMPROMISED_DATA;
  return GuLogReady()?EFI_SUCCESS:EFI_DEVICE_ERROR;
}
static EFI_STATUS VerifySelectors(const char *phase) {
  UINT32 ss0=GuRead32(GU_FEAT_SS0_OFFSET),ss1=GuRead32(GU_FEAT_SS1_OFFSET),plm=GuRead32(GU_FEAT_PLM_OFFSET);
  GuLog("%s SS0=0x%08x SS1=0x%08x FEAT_PLM=0x%08x\n",phase,ss0,ss1,plm);
  GuLog("%s unlock_matched=%u; handoff checks GPU accessibility separately\n",phase,ss0==0x88888888 && ss1==8);
#if defined(GU_ARCH_TURING) && GU_ARCH_TURING
  GuLog("%s effective speed readout=skipped-tu-profile\n",phase);
  BOOLEAN arch_ok=((plm&0xffff0000U)!=0xbadf0000U) && (plm==GU_EXPECTED_POST_FLR_PLM);
#elif !defined(GU_ARCH_ADA) || GU_ARCH_ADA
  UINT32 effective=GuRead32(0x823818);
  GuLog("%s effective speed readout=%#x\n",phase,effective);
  BOOLEAN arch_ok=((effective&0x07ffffffU)==0) && (plm==GU_EXPECTED_POST_FLR_PLM);
#else
  GuLog("%s effective speed readout=skipped-ga-profile\n",phase);
  BOOLEAN arch_ok=((plm&0xffff0000U)!=0xbadf0000U) && (plm==GU_EXPECTED_POST_FLR_PLM);
#endif
  return !Gu.fault && GuLogReady() && ss0==0x88888888 && ss1==8 && arch_ok
    ? EFI_SUCCESS : EFI_DEVICE_ERROR;
}
static EFI_STATUS RestoreDisplayForWindows(EFI_HANDLE Driver) {
  if(!WindowsImage || !Driver || !GuScreenDetached || !GuSafeToReturn() || !Gu.quiesced ||
     Gu.flrs!=1 || Gu.allocations || Gu.dma_count || !Gu.owned || Gu.fault)return EFI_NOT_READY;
  EFI_STATUS s=VerifySelectors("POST-FLR");if(EFI_ERROR(s))return s;
  GuLogText("stage=before_GOP_reconnect; transaction quiesced, DMA released, PCI restored\n");
  if(!GuLogReady())return EFI_DEVICE_ERROR;
  s=Gu.bs->CloseProtocol(Gu.handle,&PciGuid,Gu.image,NULL);if(EFI_ERROR(s))return s;
  Gu.owned=FALSE;
  EFI_HANDLE drivers[2]={Driver,NULL};
  s=Gu.bs->ConnectController(Gu.handle,drivers,NULL,TRUE);
  GuLog("ConnectController status=%#llx\n",(unsigned long long)s);
  if(EFI_ERROR(s))return s;
  s=GuRefreshTargetPci();if(EFI_ERROR(s))return s;
  ExpectDetached=FALSE;
  if(!DisplayCheck())return EFI_DEVICE_ERROR;
  UINT16 command=0,expected_cmd=(UINT16)InitialConfig[1];UINT32 value=0;
  s=GuConfigRead(EfiPciIoWidthUint16,4,&command);
  BOOLEAN cmd_ok=InitialBootBme?((command&~4U)==(expected_cmd&~4U)):(command==expected_cmd && !(command&4));
  if(EFI_ERROR(s)||!cmd_ok)return EFI_DEVICE_ERROR;
  for(UINT32 offset=0x10;offset<=0x24;offset+=4) {
    s=GuConfigRead(EfiPciIoWidthUint32,offset,&value);
    if(EFI_ERROR(s)||value!=InitialConfig[offset/4])return EFI_DEVICE_ERROR;
  }
  s=VerifySelectors("POST-GOP");if(EFI_ERROR(s))return s;
  GuLogText("stage=before_StartImage; POST-GOP selectors and PCI BAR/command verified\n");
  if(!GuLogReady())return EFI_DEVICE_ERROR;
  GuScreenDetached=FALSE;
  return EFI_SUCCESS;
}
