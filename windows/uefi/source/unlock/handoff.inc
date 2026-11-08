#include "local_profile.h"
/* Modified 2026-10-21: experimental AD103 32GB GA102-pair port; see PORT-NOTES.txt. */
/* Derived from the v0.3 handoff path exercised on this user's single AD103. */
#include <Protocol/LoadedImage.h>
#include <Protocol/SimpleFileSystem.h>
#include <Protocol/DriverBinding.h>
#include <Protocol/Decompress.h>
#include <IndustryStandard/Pci22.h>
static EFI_GUID FsGuid=EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID,LoadedGuid=EFI_LOADED_IMAGE_PROTOCOL_GUID,
  HandoffBindingGuid=EFI_DRIVER_BINDING_PROTOCOL_GUID,DecompressGuid=EFI_DECOMPRESS_PROTOCOL_GUID;
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
  BOOLEAN arch_ok=((plm&0xffff0000U)!=0xbadf0000U) && (plm==GU_EXPECTED_POST_FLR_PLM || plm==0xffffffefU || plm==0xffffff8fU);
#elif !defined(GU_ARCH_ADA) || GU_ARCH_ADA
  UINT32 effective=GuRead32(0x823818);
  GuLog("%s effective speed readout=%#x\n",phase,effective);
  BOOLEAN arch_ok=((effective&0x07ffffffU)==0) && (plm==GU_EXPECTED_POST_FLR_PLM);
#else
  GuLog("%s effective speed readout=skipped-ga-profile\n",phase);
  BOOLEAN arch_ok=((plm&0xffff0000U)!=0xbadf0000U) && (plm==GU_EXPECTED_POST_FLR_PLM || plm==0xffffff8fU);
#endif
  return !Gu.fault && GuLogReady() && ss0==0x88888888 && ss1==8 && arch_ok
    ? EFI_SUCCESS : EFI_DEVICE_ERROR;
}
static VOID ConnectTargetGopChildrenNonRecursive(VOID) {
  EFI_HANDLE *handles=NULL;UINTN count=0;
  if(EFI_ERROR(Gu.bs->LocateHandleBuffer(ByProtocol,&GopGuid,NULL,&count,&handles)) || !handles)return;
  for(UINTN i=0;i<count;i++) {
    EFI_DEVICE_PATH_PROTOCOL *path=NULL;EFI_HANDLE parent=NULL;
    if(!EFI_ERROR(Gu.bs->HandleProtocol(handles[i],&PathGuid,(VOID**)&path)) && path) {
      if(!EFI_ERROR(Gu.bs->LocateDevicePath(&PciGuid,&path,&parent)) && parent==Gu.handle) {
        EFI_GRAPHICS_OUTPUT_PROTOCOL *g=NULL;
        if(!EFI_ERROR(Gu.bs->HandleProtocol(handles[i],&GopGuid,(VOID**)&g)) && g && g->Mode &&
           !g->Mode->FrameBufferBase && !g->Mode->FrameBufferSize && g->SetMode) {
          g->SetMode(g,0);
        }
        Gu.bs->ConnectController(handles[i],NULL,NULL,FALSE);
      }
    }
  }
  GuFree(handles);
}
static EFI_STATUS GuStartNativeGopFromProm(VOID) {
  if(!Gu.bar_base || !Gu.bs->LocateProtocol || !Gu.bs->LoadImage || !Gu.bs->StartImage)return EFI_UNSUPPORTED;
  UINTN scan_bytes=0x60000U;
  UINT8 *rom=GuAlloc(scan_bytes);
  if(!rom)return EFI_OUT_OF_RESOURCES;
  GuCopyFromIo(rom,(VOID*)(UINTN)(Gu.bar_base+GU_PROM_BAR_OFFSET),scan_bytes);
  if(Gu.fault){GuFree(rom);return EFI_DEVICE_ERROR;}
  UINTN pos=0;EFI_STATUS result=EFI_NOT_FOUND;
  while(pos+sizeof(EFI_PCI_EXPANSION_ROM_HEADER)<scan_bytes) {
    UINT16 sig=(UINT16)rom[pos]|((UINT16)rom[pos+1]<<8);
    if(sig!=0xaa55U)break;
    UINT16 pcir_off=(UINT16)rom[pos+0x18]|((UINT16)rom[pos+0x19]<<8);
    if(!pcir_off || pos+pcir_off+sizeof(PCI_DATA_STRUCTURE)>scan_bytes)break;
    const PCI_DATA_STRUCTURE *pcir=(const PCI_DATA_STRUCTURE*)(rom+pos+pcir_off);
    if(pcir->Signature!=PCI_DATA_STRUCTURE_SIGNATURE)break;
    UINTN img_bytes=(UINTN)pcir->ImageLength*512U;
    if(!img_bytes || pos+img_bytes>scan_bytes)break;
    if(pcir->CodeType==0x03U) {
      const EFI_PCI_EXPANSION_ROM_HEADER *ehdr=(const EFI_PCI_EXPANSION_ROM_HEADER*)(rom+pos);
      UINT16 hdr_off=ehdr->EfiImageHeaderOffset;
      if(ehdr->EfiSignature==EFI_PCI_EXPANSION_ROM_HEADER_EFISIGNATURE && hdr_off>0 && hdr_off<img_bytes) {
        VOID *src=rom+pos+hdr_off;
        UINT32 src_size=(UINT32)(img_bytes-hdr_off);
        VOID *pe_buf=NULL,*scratch=NULL;UINT32 pe_size=0,scratch_size=0;BOOLEAN allocated_pe=FALSE;
        if(ehdr->CompressionType==1U) {
          EFI_DECOMPRESS_PROTOCOL *decomp=NULL;
          EFI_STATUS ds=Gu.bs->LocateProtocol(&DecompressGuid,NULL,(VOID**)&decomp);
          if(!EFI_ERROR(ds) && decomp && decomp->GetInfo && decomp->Decompress) {
            ds=decomp->GetInfo(decomp,src,src_size,&pe_size,&scratch_size);
            if(!EFI_ERROR(ds) && pe_size>64 && pe_size<=4U*1024U*1024U && scratch_size<=4U*1024U*1024U) {
              pe_buf=GuAlloc(pe_size);
              scratch=scratch_size?GuAlloc(scratch_size):NULL;
              if(pe_buf && (!scratch_size || scratch)) {
                allocated_pe=TRUE;
                ds=decomp->Decompress(decomp,src,src_size,pe_buf,pe_size,scratch,scratch_size);
                if(EFI_ERROR(ds)){GuFree(pe_buf);pe_buf=NULL;allocated_pe=FALSE;}
              } else {
                if(pe_buf){GuFree(pe_buf);pe_buf=NULL;}
              }
              if(scratch)GuFree(scratch);
            }
          }
        } else if(ehdr->CompressionType==0U) {
          pe_buf=src;pe_size=src_size;
        }
        if(pe_buf && pe_size>64) {
          EFI_HANDLE gop_img=NULL;
          EFI_STATUS ls=Gu.bs->LoadImage(FALSE,Gu.image,NULL,pe_buf,pe_size,&gop_img);
          GuLog("Native-GOP ROM LoadImage: offset=%#zx size=%u status=%#llx\n",pos,pe_size,(unsigned long long)ls);
          if(!EFI_ERROR(ls) && gop_img) {
            EFI_STATUS ss=Gu.bs->StartImage(gop_img,NULL,NULL);
            GuLog("Native-GOP ROM StartImage: status=%#llx\n",(unsigned long long)ss);
            if(!EFI_ERROR(ss)) {
              EFI_DRIVER_BINDING_PROTOCOL *b=NULL;
              if(EFI_ERROR(Gu.bs->HandleProtocol(gop_img,&HandoffBindingGuid,(VOID**)&b)) || !b) {
                EFI_HANDLE *bhs=NULL;UINTN bn=0;
                if(!EFI_ERROR(Gu.bs->LocateHandleBuffer(ByProtocol,&HandoffBindingGuid,NULL,&bn,&bhs)) && bhs) {
                  for(UINTN k=0;k<bn;k++) {
                    EFI_DRIVER_BINDING_PROTOCOL *cand=NULL;
                    if(!EFI_ERROR(Gu.bs->HandleProtocol(bhs[k],&HandoffBindingGuid,(VOID**)&cand)) &&
                       cand && cand->ImageHandle==gop_img){b=cand;break;}
                  }
                  GuFree(bhs);
                }
              }
              if(b && b->Supported && b->Start) {
                EFI_STATUS sup=b->Supported(b,Gu.handle,NULL);
                EFI_STATUS st=EFI_ERROR(sup)?sup:b->Start(b,Gu.handle,NULL);
                GuLog("Native-GOP ROM DriverBinding: Supported=%#llx Start=%#llx\n",(unsigned long long)sup,(unsigned long long)st);
                if(!EFI_ERROR(st)) {
                  ConnectTargetGopChildrenNonRecursive();
                  result=EFI_SUCCESS;
                }
              }
            }
          }
        }
        if(allocated_pe && pe_buf)GuFree(pe_buf);
      }
      break;
    }
    if(pcir->Indicator&0x80U)break;
    pos+=img_bytes;
  }
  GuFree(rom);
  return result;
}
static EFI_STATUS RestoreDisplayForWindows(EFI_HANDLE Driver) {
  if(!WindowsImage || !Driver || !GuScreenDetached || !GuSafeToReturn() || !Gu.quiesced ||
     Gu.flrs!=1 || Gu.allocations || Gu.dma_count || !Gu.owned || Gu.fault)return EFI_NOT_READY;
  EFI_STATUS s=VerifySelectors("POST-FLR");if(EFI_ERROR(s))return s;
  GuLogText("stage=before_GOP_reconnect; transaction quiesced, DMA released, PCI restored\n");
  GuCheckpointReport();
  if(!GuLogReady())return EFI_DEVICE_ERROR;
  s=Gu.bs->CloseProtocol(Gu.handle,&PciGuid,Gu.image,NULL);if(EFI_ERROR(s))return s;
  Gu.owned=FALSE;
  EFI_DRIVER_BINDING_PROTOCOL *binding=NULL;
  EFI_STATUS bs_lookup=Gu.bs->HandleProtocol(Driver,&HandoffBindingGuid,(VOID**)&binding);
  BOOLEAN has_explicit_binding=(!EFI_ERROR(bs_lookup) && binding && binding->Supported && binding->Start);
  BOOLEAN is_csm_bios_video=(PendingOwner.size>0 && PendingOwner.size<=65536U) || (PendingOwner.version>0 && PendingOwner.version<=0x30U);
  if(has_explicit_binding || (InitialBootBme && is_csm_bios_video)) {
    /* Real UEFI hardware path: never call generic PCI-level ConnectController(Gu.handle, ...),
       which invokes resident CSM BiosVideoDxe (Int10h) and deadlocks after PCIe FLR (#106/#107/#133). */
    EFI_STATUS bind_status=EFI_UNSUPPORTED;
    if(has_explicit_binding && !is_csm_bios_video) {
      EFI_STATUS sup=binding->Supported(binding,Gu.handle,NULL);
      bind_status=EFI_ERROR(sup)?sup:binding->Start(binding,Gu.handle,NULL);
      GuLog("Explicit GOP DriverBinding: Supported=%#llx Start=%#llx\n",(unsigned long long)sup,(unsigned long long)bind_status);
      if(!EFI_ERROR(bind_status))ConnectTargetGopChildrenNonRecursive();
    } else {
      GuLog("CSM BiosVideoDxe owner detected (bytes=%llu version=%#x); bypassing Int10h and starting Native GOP from OptionROM\n",
        (unsigned long long)PendingOwner.size,PendingOwner.version);
    }
    if(EFI_ERROR(bind_status)) {
      EFI_STATUS nat_status=GuStartNativeGopFromProm();
      GuLog("Native-GOP ROM recovery status=%#llx\n",(unsigned long long)nat_status);
    }
    GuCheckpointReport();
  } else {
    EFI_HANDLE drivers[2]={Driver,NULL};
    EFI_STATUS conn_status=Gu.bs->ConnectController(Gu.handle,drivers,NULL,TRUE);
    GuLog("ConnectController status=%#llx\n",(unsigned long long)conn_status);
    if(EFI_ERROR(conn_status) && !InitialBootBme)return conn_status;
  }
  s=GuRefreshTargetPci();if(EFI_ERROR(s))return s;
  if(InitialBootBme || has_explicit_binding || is_csm_bios_video) {
    /* Ensure BME is cleared and MMIO decode is active after GOP driver Start(). */
    UINT16 cur_cmd=0;
    if(!EFI_ERROR(GuConfigRead(EfiPciIoWidthUint16,4,&cur_cmd))) {
      if(cur_cmd&4U)GuClearMaster();
      if(!(cur_cmd&2U) && Gu.pci && Gu.pci->Attributes) {
        Gu.pci->Attributes(Gu.pci,EfiPciIoAttributeOperationEnable,EFI_PCI_IO_ATTRIBUTE_MEMORY,NULL);
      }
    }
  }
  ExpectDetached=FALSE;
  BOOLEAN disp_ok=DisplayCheck();
  if(!disp_ok) {
    if(!InitialBootBme && !has_explicit_binding && !is_csm_bios_video)return EFI_DEVICE_ERROR;
    GuLogText("GOP reconnect deferred to Windows Boot Manager (POST-GOP selectors and BARs verified)\n");
  }
  UINT16 command=0,expected_cmd=(UINT16)InitialConfig[1];UINT32 value=0;
  s=GuConfigRead(EfiPciIoWidthUint16,4,&command);
  BOOLEAN cmd_ok=(InitialBootBme || has_explicit_binding || is_csm_bios_video)?((command&2U)!=0):(command==expected_cmd && !(command&4));
  if(EFI_ERROR(s)||!cmd_ok)return EFI_DEVICE_ERROR;
  for(UINT32 offset=0x10;offset<=0x24;offset+=4) {
    s=GuConfigRead(EfiPciIoWidthUint32,offset,&value);
    if(EFI_ERROR(s)||value!=InitialConfig[offset/4])return EFI_DEVICE_ERROR;
  }
  s=VerifySelectors("POST-GOP");if(EFI_ERROR(s))return s;
  GuLogText("stage=before_StartImage; POST-GOP selectors and PCI BAR/command verified\n");
  GuCheckpointReport();
  if(!GuLogReady())return EFI_DEVICE_ERROR;
  if(disp_ok)GuScreenDetached=FALSE;
  return EFI_SUCCESS;
}
