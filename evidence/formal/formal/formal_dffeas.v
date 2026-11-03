module dffeas(input d,clk,clrn,prn,ena,asdata,aload,sclr,sload,output reg q);
 parameter power_up="dontcare", is_wysiwyg="false";
 initial begin
  if(power_up=="high") q=1'b1;
  else if(power_up=="low") q=1'b0;
 end
 always @(posedge clk or negedge clrn)
  if(!clrn) q<=1'b0;
  else if(ena) q<=d;
endmodule
