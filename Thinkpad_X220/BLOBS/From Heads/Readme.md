Blobs from compiled Heads (for 8Mb SPI flash)

ME.BIN
wget  https://download.lenovo.com/ibmdl/pub/pc/pccbbs/mobiles/83rf46ww.exe
innoextract 83rf46ww.exe
python3 blobs/xx20/me7_update_parser.py -O blobs/xx20/me.bin app/ME7_5M_UPD_Production.bin 

ifd.bin is from an X220 and already ME partition resided to the new minimized size.  The layout.txt has these updated sized and can be used with ifdtool to modify partition if needed. 

Manually regenerate gbe.bin:
blobs/x220/gbe.bin is generated per bincfg from the following coreboot patch: https://review.coreboot.org/c/coreboot/+/44510
And then by following those instructions:
# Use this target to generate GbE for X220/x230
gen-gbe-82579LM:
	cd build/coreboot-4.8.1/util/bincfg/
	make
	./bincfg gbe-82579LM.spec gbe-82579LM.set gbe1.bin
	# duplicate binary as per spec
	cat gbe1.bin gbe1.bin > ../../../../blobs/xx20/gbe.bin
	rm -f gbe1.bin
	cd - 
