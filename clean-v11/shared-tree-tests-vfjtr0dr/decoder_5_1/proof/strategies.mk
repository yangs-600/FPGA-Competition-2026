.DEFAULT_GOAL := all

strategies/decoder_5_1.z/simple/status:
	@echo "Running strategy 'simple' on 'decoder_5_1.z'.."
	@bash -c "cd strategies/decoder_5_1.z/simple; source run.sh"

strategies/decoder_5_1.z/pdr/status: strategies/decoder_5_1.z/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'decoder_5_1.z'.."; \
		bash -c "cd strategies/decoder_5_1.z/pdr; source run.sh"; \
	fi

strategies/decoder_5_1.y/simple/status:
	@echo "Running strategy 'simple' on 'decoder_5_1.y'.."
	@bash -c "cd strategies/decoder_5_1.y/simple; source run.sh"

strategies/decoder_5_1.y/pdr/status: strategies/decoder_5_1.y/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'decoder_5_1.y'.."; \
		bash -c "cd strategies/decoder_5_1.y/pdr; source run.sh"; \
	fi

.PHONY: all summary
all: strategies/decoder_5_1.y/pdr/status strategies/decoder_5_1.z/pdr/status
	$(MAKE) -f strategies.mk summary
summary:
	@rc=0 ; \
	while read f; do \
		p=$${f#strategies/} ; p=$${p%/*/status} ; \
		if grep -q "PASS" $$f ; then \
			echo "* Successfully proved equivalence of partition $$p" ; \
		else \
			echo "* Failed to prove equivalence of partition $$p" ; rc=1 ; \
		fi ; \
	done < summary_targets.list ; \
	if [ "$$rc" -eq 0 ] ; then \
		echo "* Successfully proved designs equivalent" ; \
	fi
