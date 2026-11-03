.DEFAULT_GOAL := all

strategies/test4.only_5b/simple/status:
	@echo "Running strategy 'simple' on 'test4.only_5b'.."
	@bash -c "cd strategies/test4.only_5b/simple; source run.sh"

strategies/test4.only_5b/pdr/status: strategies/test4.only_5b/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test4.only_5b'.."; \
		bash -c "cd strategies/test4.only_5b/pdr; source run.sh"; \
	fi

strategies/test4.dataout/simple/status:
	@echo "Running strategy 'simple' on 'test4.dataout'.."
	@bash -c "cd strategies/test4.dataout/simple; source run.sh"

strategies/test4.dataout/pdr/status: strategies/test4.dataout/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test4.dataout'.."; \
		bash -c "cd strategies/test4.dataout/pdr; source run.sh"; \
	fi

strategies/test4.datain_5bis7/simple/status:
	@echo "Running strategy 'simple' on 'test4.datain_5bis7'.."
	@bash -c "cd strategies/test4.datain_5bis7/simple; source run.sh"

strategies/test4.datain_5bis7/pdr/status: strategies/test4.datain_5bis7/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test4.datain_5bis7'.."; \
		bash -c "cd strategies/test4.datain_5bis7/pdr; source run.sh"; \
	fi

strategies/test4.data_dp/simple/status:
	@echo "Running strategy 'simple' on 'test4.data_dp'.."
	@bash -c "cd strategies/test4.data_dp/simple; source run.sh"

strategies/test4.data_dp/pdr/status: strategies/test4.data_dp/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test4.data_dp'.."; \
		bash -c "cd strategies/test4.data_dp/pdr; source run.sh"; \
	fi

strategies/test4.data_dn/simple/status:
	@echo "Running strategy 'simple' on 'test4.data_dn'.."
	@bash -c "cd strategies/test4.data_dn/simple; source run.sh"

strategies/test4.data_dn/pdr/status: strategies/test4.data_dn/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test4.data_dn'.."; \
		bash -c "cd strategies/test4.data_dn/pdr; source run.sh"; \
	fi

.PHONY: all summary
all: strategies/test4.data_dn/pdr/status strategies/test4.data_dp/pdr/status strategies/test4.datain_5bis7/pdr/status strategies/test4.dataout/pdr/status strategies/test4.only_5b/pdr/status
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
