.DEFAULT_GOAL := all

strategies/test1.por6_out/simple/status:
	@echo "Running strategy 'simple' on 'test1.por6_out'.."
	@bash -c "cd strategies/test1.por6_out/simple; source run.sh"

strategies/test1.por6_out/pdr/status: strategies/test1.por6_out/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test1.por6_out'.."; \
		bash -c "cd strategies/test1.por6_out/pdr; source run.sh"; \
	fi

strategies/test1.inter0009_out/simple/status:
	@echo "Running strategy 'simple' on 'test1.inter0009_out'.."
	@bash -c "cd strategies/test1.inter0009_out/simple; source run.sh"

strategies/test1.inter0009_out/pdr/status: strategies/test1.inter0009_out/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test1.inter0009_out'.."; \
		bash -c "cd strategies/test1.inter0009_out/pdr; source run.sh"; \
	fi

strategies/test1.inter0008_out/simple/status:
	@echo "Running strategy 'simple' on 'test1.inter0008_out'.."
	@bash -c "cd strategies/test1.inter0008_out/simple; source run.sh"

strategies/test1.inter0008_out/pdr/status: strategies/test1.inter0008_out/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test1.inter0008_out'.."; \
		bash -c "cd strategies/test1.inter0008_out/pdr; source run.sh"; \
	fi

strategies/test1.inter0007_out/simple/status:
	@echo "Running strategy 'simple' on 'test1.inter0007_out'.."
	@bash -c "cd strategies/test1.inter0007_out/simple; source run.sh"

strategies/test1.inter0007_out/pdr/status: strategies/test1.inter0007_out/simple/status
	@if grep PASS $^ >/dev/null ; then \
		echo "PASS (cached)" > $@; \
	elif grep FAIL $^ >/dev/null ; then \
		echo "FAIL (cached)" > $@; \
	else \
		echo "Running strategy 'pdr' on 'test1.inter0007_out'.."; \
		bash -c "cd strategies/test1.inter0007_out/pdr; source run.sh"; \
	fi

.PHONY: all summary
all: strategies/test1.inter0007_out/pdr/status strategies/test1.inter0008_out/pdr/status strategies/test1.inter0009_out/pdr/status strategies/test1.por6_out/pdr/status
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
