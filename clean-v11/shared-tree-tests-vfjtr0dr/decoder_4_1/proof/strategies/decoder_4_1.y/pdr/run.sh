STATUS=ERROR
sby -f decoder_4_1.y.sby > /dev/null && STATUS=$(awk '{print $1}' decoder_4_1.y/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'decoder_4_1.y' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'decoder_4_1.y' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'decoder_4_1.y' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'decoder_4_1.y' using strategy 'pdr': timeout"
    ;;
    *)
        cat decoder_4_1.y/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'decoder_4_1.y' encountered an error."
        echo "More details can be found in '/home/ubuntu/FPGA/clean-v11/shared-tree-tests-vfjtr0dr/decoder_4_1/proof/strategies/decoder_4_1.y/pdr/decoder_4_1.y/logfile.txt'."
        exit 1
    ;;
esac
exit 0

